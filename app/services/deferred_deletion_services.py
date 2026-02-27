# app/services/deferred_deletion_service.py
from typing import List, Dict
from datetime import datetime
from flask import current_app

from app.logger import get_logger
from ..repositories.deferred_deletions_repo import DeferredDeletionsRepo
from ..services.commun_service import CommunService


logger = get_logger(__name__)


class DeferredDeletionService:
    def __init__(self, app=None):
        self.app = app or current_app._get_current_object()
        self.logger = get_logger(__name__, app=self.app)
        self.deferred_repo = DeferredDeletionsRepo()
        self.commun_service = CommunService(self.app)

    def _now_utc(self) -> datetime:
        return datetime.utcnow()

    def _is_deletable(self, can_be_deleted_at) -> bool:
        if not can_be_deleted_at:
            return True
        cb = can_be_deleted_at
        try:
            if getattr(cb, "tzinfo", None):
                cb = cb.astimezone(tz=None).replace(tzinfo=None)
        except Exception:
            self.logger.exception("_is_deletable: tz normalize failed for %s", can_be_deleted_at)
            return True
        return cb <= self._now_utc()

    def _collect_deletable_hashes(self, rows) -> List[str]:
        hashes: List[str] = []
        seen = set()
        for row in rows:
            h = (getattr(row, "torrent_hash", "") or "").strip().lower()
            if not h or h in seen:
                continue
            if self._is_deletable(getattr(row, "can_be_deleted_at", None)):
                seen.add(h)
                hashes.append(h)
        return hashes
    

    def _notify_deferred_deletion(self, deleted_raw, failed_raw, absent_raw) -> bool:
        try:
            # build names lists if pairs (hash,name) provided, else empty lists
            deleted_names = [name for (_h, name) in deleted_raw] if deleted_raw and isinstance(deleted_raw[0], (list, tuple)) else []
            failed_names = [name for (_h, name) in failed_raw] if failed_raw and isinstance(failed_raw[0], (list, tuple)) else []
            absent_names = list(absent_raw or [])
            # generic notify: title + placeholders
            self.commun_service._send_notify("Deferred deletions", "—", "—", deleted_names, [], failed_names, None)
            return True
        except Exception:
            self.logger.exception("_notify_deferred_deletion: notify failed")
            return False
        
    def extract_hashes(self, m):
        if not m:
            return []
        first = m[0]
        if isinstance(first, (list, tuple)):
            return [h for (h, _n) in m if h]
        return [h for h in m if h]

    def perform_deletion_deferred(self, hashes: List[str], notify: bool = True) -> Dict:
        result = {"requested": len(hashes), "qb_deleted": [], "qb_absent": [], "qb_failed": [], "removed_deferred": 0, "notify_sent": False}

        if not hashes:
            self.logger.debug("perform_deletion_deferred: no hashes")
            return result

        # qBittorrent Deletion
        qb_out = None
        try:
            qb_out = self.commun_service.perform_qbittorrent_delete(hashes)
        except Exception:
            self.logger.exception("perform_deletion_deferred: qb delete failed")
            return result

        deleted_raw = qb_out.get("deleted", []) or []
        failed_raw = qb_out.get("failed", []) or []
        absent_raw = qb_out.get("absent", []) or []

       

        qb_deleted = self.extract_hashes(deleted_raw)
        qb_failed = self.extract_hashes(failed_raw)
        qb_absent = self.extract_hashes(absent_raw)

        result["qb_deleted"] = qb_deleted
        result["qb_failed"] = qb_failed
        result["qb_absent"] = qb_absent

        # 2) remove deferred rows for deleted or absent
        hashes_to_remove = list(set(qb_deleted + qb_absent))
        if hashes_to_remove:
            try:
                removed = self.deferred_repo.delete_many(hashes_to_remove)
                result["removed_deferred"] = int(removed)
                self.logger.info("perform_deletion_deferred: removed %d deferred rows", removed)
            except Exception:
                self.logger.exception("perform_deletion_deferred: failed to remove deferred rows %s", hashes_to_remove)

        # 3) notify via separate method
        if notify:
            notified = self._notify_deferred_deletion(deleted_raw, failed_raw, qb_absent)
            result["notify_sent"] = bool(notified)

        return result

    def process_once(self, batch_size: int = 100, notify: bool = True) -> Dict:
        summary = {"fetched": 0, "candidates": [], "deletable": [], "deletion": None}

        try:
            rows = self.deferred_repo.get_due(limit=batch_size)
        except Exception:
            self.logger.exception("process_once: get_due failed")
            return summary

        if not rows:
            self.logger.debug("process_once: none due")
            return summary

        summary["fetched"] = len(rows)
        summary["candidates"] = [(getattr(r, "torrent_hash", "") or "").strip().lower() for r in rows]
        deletable = self._collect_deletable_hashes(rows)
        summary["deletable"] = deletable

        if not deletable:
            self.logger.info("process_once: none deletable now (%d rows)", len(rows))
            return summary

        deletion_summary = self.perform_deletion_deferred(deletable, notify=notify)
        summary["deletion"] = deletion_summary

        self.logger.info("process_once: done summary=%s", summary)
        return summary