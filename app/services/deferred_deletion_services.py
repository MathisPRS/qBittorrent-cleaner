# app/services/deferred_deletion_service.py
from typing import List, Dict
from datetime import datetime
from flask import current_app
from app.logger import get_logger

from ..repositories.deferred_deletions_repo import DeferredDeletionsRepo
from ..services.commun_service import CommunService


class DeferredDeletionService:

    def __init__(self, app=None):
        self.app = app or current_app._get_current_object()
        self.logger = get_logger(__name__, app=self.app)
        self.deferred_repo = DeferredDeletionsRepo()
        self.commun_service = CommunService(self.app)



    def process_once(self, batch_size: int = 100) -> Dict:
        summary = {
            "fetched_rows": 0,
            "candidate_hashes": [],
            "deletable_hashes": [],
            "deletion_summary": {}
        }

        try:
            rows = self.deferred_repo.get_due(limit=batch_size)
        except Exception:
            self.logger.exception("process_once: deferred_repo.get_due failed")
            return summary

        if not rows:
            self.logger.info("process_once: no deferred deletions found")
            return summary

        summary["fetched_rows"] = len(rows)

        # candidates
        candidate_hashes = []
        for r in rows:
            th = (getattr(r, "torrent_hash", "") or "").strip().lower()
            if th:
                candidate_hashes.append(th)
        summary["candidate_hashes"] = candidate_hashes

        # filter deletable now
        deletable = self._collect_deletable_hashes(rows)
        summary["deletable_hashes"] = deletable

        if not deletable:
            self.logger.info("process_once: no hashes are deletable yet (will keep rows for later)")
            return summary

        # perform deletions (calls CommunService then repo.delete_many via _perform_deletions)
        deletion_summary = self._perform_deletions(deletable)
        summary["deletion_summary"] = deletion_summary

        self.logger.info("process_once: finished summary=%s", summary)
        return summary

    def _is_deletable(self, can_be_deleted_at) -> bool:
        """
        True si can_be_deleted_at est passé (UTC).
        """
        if not can_be_deleted_at:
            return True
        now = datetime.utcnow()
        # can_be_deleted_at may be timezone-aware; compare naive UTC by normalizing if needed
        try:
            c = can_be_deleted_at
            if getattr(c, "tzinfo", None):
                # convert to naive UTC for comparison
                c = c.astimezone(tz=None).replace(tzinfo=None)
        except Exception:
            # en cas d'erreur sur tz, on considère deletable pour ne pas bloquer
            self.logger.exception("_is_deletable: failed to normalize can_be_deleted_at -> consider deletable")
            return True
        return c <= now

    def _collect_deletable_hashes(self, rows) -> List[str]:
        """
        Parcourt les rows DeferredDeletion, retourne la liste unique des hashes deletable now.
        """
        hashes: List[str] = []
        seen = set()
        for r in rows:
            th = (getattr(r, "torrent_hash", "") or "").strip().lower()
            if not th or th in seen:
                continue
            can_be = getattr(r, "can_be_deleted_at", None)
            if self._is_deletable(can_be):
                seen.add(th)
                hashes.append(th)
        return hashes
    

    

    def _perform_deletions(self, hashes: List[str]) -> Dict:
        """
        Appelle les helpers existants et effectue la suppression en base pour les hashes confirmés.
        Retourne un résumé.
        """
        summary = {
            "qb_deleted": [],     # list of hashes confirmed deleted by qB
            "qb_failed": [],      # list of hashes failed at qb
            "qb_absent": [],      # list of hashes absent at qb
            "db_deleted_count": 0
        }

        if not hashes:
            return summary

        # 1) qBittorrent delete (CommunService doit renvoyer la structure attendue)
        try:
            qb_out = self.commun_service.perform_qbittorrent_delete(hashes) or {}
        except Exception:
            self.logger.exception("_perform_deletions: perform_qbittorrent_delete raised")
            qb_out = {"deleted": [], "failed": [], "absent": [], "hashes_to_delete_in_db": []}

        # normalize returned lists
        def _unwrap_pairs(lst):
            if not lst:
                return []
            if isinstance(lst[0], (list, tuple)):
                return [h for (h, _n) in lst if h]
            return [h for h in lst if h]

        summary["qb_deleted"] = _unwrap_pairs(qb_out.get("deleted", []))
        summary["qb_failed"] = _unwrap_pairs(qb_out.get("failed", []))
        summary["qb_absent"] = list(qb_out.get("absent", []) or [])
        hashes_for_db = list(qb_out.get("hashes_to_delete_in_db", []) or [])

        # 2) perform BDD delete via CommunService (if applicable)
        if hashes_for_db:
            try:
                db_result = self.commun_service.perform_bdd_delete(hashes_for_db) or {"deleted_total": 0}
                summary["db_deleted_count"] = int(db_result.get("deleted_total", 0))
            except Exception:
                self.logger.exception("_perform_deletions: perform_bdd_delete raised")
                summary["db_deleted_count"] = 0

            # 3) remove rows from deferred_deletions via repo.delete_many
            try:
                removed = self.deferred_repo.delete_many(hashes_for_db)
                self.logger.info("_perform_deletions: deferred rows removed=%s for hashes=%s", removed, hashes_for_db)
            except Exception:
                self.logger.exception("_perform_deletions: deferred_repo.delete_many failed (will retry later)")

        return summary

    