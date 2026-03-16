# app/services/deferred_deletion_service.py
from typing import List, Dict
from datetime import datetime, timedelta
from flask import current_app
from typing import Optional
from app.config import DEFFERED_DELETION_DELTA
from app.repositories.deferred_deletions_repo import DeferredDeletionsRepo
from app.repositories.torrents_repo import TorrentsRepo
from app.logger import get_logger
from app.services.commun_services import CommunService
from app.services.scheduler_services import SchedulerService

logger = get_logger(__name__)


class DeferredDeletionService:
    def __init__(self, app=None):
        self.app = app or current_app._get_current_object()
        self.logger = get_logger(__name__, app=self.app)
        self.commun_services = CommunService(self.app)
        self.scheduler_services = SchedulerService(self.app)

        self.deferred_deletion_repo = DeferredDeletionsRepo()
        self.torrents_repo = TorrentsRepo()
        self.delta = timedelta(hours=DEFFERED_DELETION_DELTA)

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
            deleted_names = [name for (_h, name) in deleted_raw] if deleted_raw and isinstance(deleted_raw[0], (list, tuple)) else []
            failed_names = [name for (_h, name) in failed_raw] if failed_raw and isinstance(failed_raw[0], (list, tuple)) else []
            absent_names = list(absent_raw or [])
            self.commun_services._send_notify("Deferred deletions", "—", "—", deleted_names, [], failed_names, None)
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
            qb_out = self.commun_services.perform_qbittorrent_delete(hashes)
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
                removed = self.deferred_deletion_repo.delete_many(hashes_to_remove)
                result["removed_deferred"] = int(removed)
                self.logger.info("perform_deletion_deferred: removed %d deferred rows", removed)
            except Exception:
                self.logger.exception("perform_deletion_deferred: failed to remove deferred rows %s", hashes_to_remove)

        # 3) notify via separate method
        if notify:
            notified = self._notify_deferred_deletion(deleted_raw, failed_raw, qb_absent)
            result["notify_sent"] = bool(notified)

        return result

    # -----------------------------
    # Deferred_deletion helpers
    # -----------------------------
    def filter_deferred_deletion_hash(self, candidate_hashes: List[str]) -> List[str]:
        if not candidate_hashes:
            return []

        ready_to_delete: List[str] = []
        seen_hashes = set()
        instant_delete_indexers = {"nyaa", "torr9", "c411"}

        for torrent_hash in candidate_hashes:
            normalized_hash = (torrent_hash or "").strip().lower()
            if not normalized_hash or normalized_hash in seen_hashes:
                continue
            seen_hashes.add(normalized_hash)

            # Check indexer first
            indexer = None
            try:
                indexer = self.torrents_repo.get_indexer_from_hash(normalized_hash)
            except Exception:
                self.logger.exception("filter_deferred_deletion_hash: failed to get indexer for hash=%s", normalized_hash)
            if indexer in instant_delete_indexers:
                self.logger.info("filter_deferred_deletion_hash: instant delete allowed for hash=%s indexer=%s", normalized_hash, indexer)
                ready_to_delete.append(normalized_hash)
                continue

            # ---------------------------------
            # Normal seed-time logic
            # ---------------------------------
            try:
                can_delete = self.calculate_delta(normalized_hash)
            except Exception:
                self.logger.exception("filter_deferred_deletion_hash: calculate_delta failed for hash=%s -> marking ready", normalized_hash)
                can_delete = True

            if can_delete:
                ready_to_delete.append(normalized_hash)
                continue

            # ---------------------------------
            # Move to deferred deletion
            # ---------------------------------
            name = None
            try:
                info = self.torrents_repo.get_by_hash(normalized_hash)
                name = getattr(info, "name", None)
            except Exception:
                self.logger.debug("filter_deferred_deletion_hash: failed to resolve name for hash=%s", normalized_hash)

            try:
                self.migrate_deferred_torrent(normalized_hash, name=name)
            except Exception:
                self.logger.exception("filter_deferred_deletion_hash: migrate_deferred_torrent failed for hash=%s", normalized_hash)

        self.logger.info("filter_deferred_deletion_hash: ready_to_delete_count=%d deferred_count=%d", len(ready_to_delete), len(seen_hashes) - len(ready_to_delete))
        return ready_to_delete


    def calculate_delta(self, torrent_hash: str) -> bool:
        if not torrent_hash:
            self.logger.debug("calculate_delta: empty hash -> considered ready")
            return True

        try:
            created_at = self.torrents_repo.get_attr_created_at_by_hash(torrent_hash)
        except Exception:
            self.logger.exception("calculate_delta: failed to fetch created_at for hash=%s -> consider ready", torrent_hash)
            return True

        if created_at is None:
            # pas d'info en DB : considérer prêt à suppression (on ne bloque pas)
            self.logger.debug("calculate_delta: no created_at for hash=%s -> considered ready", torrent_hash)
            return True

        ca = created_at
        if getattr(ca, "tzinfo", None):
            try:
                ca = ca.astimezone(tz=None).replace(tzinfo=None)
            except Exception:
                # fallback keep as-is
                pass

        now = datetime.utcnow()
        age = now - ca
        ready = age >= self.delta
        self.logger.debug(
            "calculate_delta: hash=%s created_at=%s age=%s ready=%s",
            torrent_hash, ca.isoformat(), age, ready
        )
        return ready


    def migrate_deferred_torrent(self, torrent_hash: str, name: Optional[str] = None) -> None:
            if not torrent_hash:
                self.logger.debug("migrate_deferred_torrent: empty hash -> skip")
                return

            now = datetime.utcnow()
            try:
                created_at = self.torrents_repo.get_attr_created_at_by_hash(torrent_hash)
            except Exception:
                self.logger.exception("migrate_deferred_torrent: failed to read created_at for hash=%s", torrent_hash)
                created_at = None

            if created_at:
                ca = created_at
                if getattr(ca, "tzinfo", None):
                    try:
                        ca = ca.astimezone(tz=None).replace(tzinfo=None)
                    except Exception:
                        pass
                can_be_deleted_at = ca + self.delta
            else:
                can_be_deleted_at = now + self.delta

            try:
                created = self.deferred_deletion_repo.create_if_not_exists(
                    torrent_hash=torrent_hash,
                    name=name,
                    can_be_deleted_at=can_be_deleted_at
                )
                if created:
                    self.logger.info("migrate_deferred_torrent: deferred row created for hash=%s can_be=%s",
                                    torrent_hash, can_be_deleted_at)
                    try:
                        task_id =self.scheduler_services.schedule_deferred_for_hash(torrent_hash, can_be_deleted_at)
                        if task_id:
                            try:
                                self.deferred_deletion_repo.set_task_id_for_hash(torrent_hash, task_id)
                            except Exception:
                                self.logger.exception("migrate_deferred_torrent: failed to persist task_id for %s", torrent_hash)
                            self.logger.info("migrate_deferred_torrent: scheduled celery task %s for %s", task_id, torrent_hash)
                    except Exception:
                        self.logger.exception("migrate_deferred_torrent: schedule_deferred_for_hash failed for %s", torrent_hash)
                else:
                    self.logger.debug("migrate_deferred_torrent: deferred row already exists for hash=%s", torrent_hash)
            except Exception:
                self.logger.exception("migrate_deferred_torrent: failed to create deferred row for hash=%s", torrent_hash)

