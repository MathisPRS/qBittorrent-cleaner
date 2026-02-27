from datetime import datetime, timedelta
import os
from typing import List, Optional

from sqlalchemy import Tuple
from ..repositories.torrents_repo import TorrentsRepo
from ..repositories.movies_repo import MoviesRepo
from ..repositories.deferred_deletions_repo import DeferredDeletionsRepo
from ..adapters.qbittorrent_adapter import QbittorrentAdapter
from ..adapters.gotify_adapter import notify_gotify
from ..extensions import db

from ..config import QBIT_HOST, QBIT_PASS, QBIT_USER
from app.logger import get_logger
from sqlalchemy.exc import SQLAlchemyError


class CommunService:
    def __init__(self, app):
        self.app = app
        self.logger = get_logger(__name__, app=app)
        self.torrent_repo = TorrentsRepo()
        self.movie_repo = MoviesRepo()
        self.deferred_deletion_repo = DeferredDeletionsRepo()
        self.qb = QbittorrentAdapter()
        self.delta = timedelta(hours=48)

    # -----------------------------
    # Deletion helpers
    # -----------------------------

    def perform_deletion(self, ready_hashes):
        # Delete QBITTORRENT
        try:
            qb_out = self.perform_qbittorrent_delete(ready_hashes)
        except Exception:
            self.logger.exception("delete_ready_hashes_and_notify: perform_qbittorrent_delete failed")
            qb_out = {"deleted": [], "failed": [], "absent": [], "hashes_to_delete_in_db": []}

        deleted = qb_out.get("deleted", [])
        failed = qb_out.get("failed", [])
        absent = qb_out.get("absent", [])
        hashes_for_db = qb_out.get("hashes_to_delete_in_db", [])

        # Delete BDD
        try:
            db_result = self.perform_bdd_delete(hashes_for_db)
        except Exception:
            self.logger.exception("delete_ready_hashes_and_notify: perform_bdd_delete failed")
            db_result = {"deleted_total": 0}

        # prepare notification lists
        deleted_names = [n for (_h, n) in deleted if n]
        absent_names = list(absent) if absent else []
        failed_names = [n for (_h, n) in failed if n]

        return {"deleted_names": deleted_names,
                "absent_names": absent_names,
                "failed_names": failed_names,
                "db_result": db_result}
    

    def perform_qbittorrent_delete(self, hashes_to_delete: list) -> dict:

        qb_result = self.qb.delete_torrents(hashes_to_delete, delete_files=True)

        deleted = qb_result.get("deleted", []) or []
        failed = qb_result.get("failed", []) or []
        absent = qb_result.get("absent", []) or []

        deleted_hashes = [hash_value for (hash_value, _name) in deleted]
        hashes_to_delete_in_db = deleted_hashes + absent

        if deleted_hashes:
            self.logger.info("[qBittorrent] deleted hashes (%d):", len(deleted_hashes))
            for h in deleted_hashes:
                self.logger.info("  - %s", h)

        if absent:
            self.logger.info("[qBittorrent] absent hashes (%d):", len(absent))
            for h in absent:
                self.logger.info("  - %s", h)

        if failed:
            failed_hashes = [hash_value for (hash_value, _name) in failed]
            self.logger.warning("[qBittorrent] failed hashes (%d):", len(failed_hashes))
            for h in failed_hashes:
                self.logger.warning("  - %s", h)
                
        return {
            "deleted": deleted,
            "failed": failed,
            "absent": absent,
            "hashes_to_delete_in_db": hashes_to_delete_in_db,
        }

    def perform_bdd_delete(self, hashes_to_delete: list) -> dict:
       
        if not hashes_to_delete:
            return {"deleted_total": 0, "deleted_hashes": [], "skipped_hashes": []}

        normalized_requested = []
        seen = set()
        for h in hashes_to_delete:
            nh = (h or "").strip().lower()
            if nh and nh not in seen:
                seen.add(nh)
                normalized_requested.append(nh)

        deleted_hashes = []
        skipped_hashes = []

        try:
            for torrent_hash in normalized_requested:
                try:
                    rows_deleted = self.torrent_repo.delete_by_hash(torrent_hash)
                    if rows_deleted:
                        deleted_hashes.append(torrent_hash)
                        self.logger.info("[BBDD] removed torrent from DB (hash=%s, rows=%d)", torrent_hash, rows_deleted)
                    else:
                        skipped_hashes.append(torrent_hash)
                        self.logger.info("[BBDD] nothing to remove for hash=%s (already absent)", torrent_hash)
                except Exception as err:
                    # per-hash failure -> mark as skipped but continue
                    self.logger.exception("[BBDD] failed to delete hash=%s: %s", torrent_hash, err)
                    skipped_hashes.append(torrent_hash)

            # commit once for the batch
            try:
                db.session.commit()
            except Exception as err_commit:
                self.logger.exception("[BBDD] commit failed after deletions: %s", err_commit)
                try:
                    db.session.rollback()
                except Exception:
                    self.logger.exception("[BBDD] rollback failed after commit error")
                # if commit failed, consider all as skipped (we didn't persist)
                return {"deleted_total": 0, "deleted_hashes": [], "skipped_hashes": normalized_requested}

        except SQLAlchemyError:
            self.logger.exception("[BBDD] fatal SQLAlchemyError during batch delete; rolling back")
            try:
                db.session.rollback()
            except Exception:
                self.logger.exception("[BBDD] rollback failed after SQLAlchemyError")
            return {"deleted_total": 0, "deleted_hashes": [], "skipped_hashes": normalized_requested}

        return {
            "deleted_total": len(deleted_hashes),
            "deleted_hashes": deleted_hashes,
            "skipped_hashes": skipped_hashes,
        }
    
    # -----------------------------
    # Deferred_deletion helpers
    # -----------------------------
    def filter_deferred_deletion_hash(self, candidate_hashes: List[str]) -> List[str]:
        if not candidate_hashes:
            return []

        ready_to_delete: List[str] = []
        seen = set()

        for h in candidate_hashes:
            nh = (h or "").strip().lower()
            if not nh or nh in seen:
                continue
            seen.add(nh)

            try:
                can_delete = self.calculate_delta(nh)
            except Exception:
                self.logger.exception("filter_deferred_deletion_hash: calculate_delta failed for hash=%s -> marking ready", nh)
                can_delete = True

            if can_delete:
                ready_to_delete.append(nh)
                continue

            name = None
            try:
                info = self.torrent_repo.get_by_hash(nh)
                name = getattr(info, "name", None)
            except Exception:
                # best-effort: if we can't read name, proceed with None
                self.logger.debug("filter_deferred_deletion_hash: failed to resolve name for hash=%s", nh)

            # do migration (create deferred row + remove torrent row)
            try:
                self.migrate_deferred_torrent(nh, name=name)
            except Exception:
                # do not break the loop; log and continue
                self.logger.exception("filter_deferred_deletion_hash: migrate_deferred_torrent failed for hash=%s", nh)

        self.logger.info("filter_deferred_deletion_hash: ready_to_delete_count=%d deferred_count=%d", len(ready_to_delete), len(seen) - len(ready_to_delete))
        return ready_to_delete


    def calculate_delta(self, torrent_hash: str) -> bool:
        if not torrent_hash:
            self.logger.debug("calculate_delta: empty hash -> considered ready")
            return True

        try:
            created_at = self.torrent_repo.get_attr_created_at_by_hash(torrent_hash)
        except Exception:
            # si la lecture DB échoue, on évite de bloquer la suppression:
            self.logger.exception("calculate_delta: failed to fetch created_at for hash=%s -> consider ready", torrent_hash)
            return True

        if created_at is None:
            # pas d'info en DB : considérer prêt à suppression (on ne bloque pas)
            self.logger.debug("calculate_delta: no created_at for hash=%s -> considered ready", torrent_hash)
            return True

        # normalize timezone-aware -> naive UTC for comparison
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
            created_at = self.torrent_repo.get_attr_created_at_by_hash(torrent_hash)
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
            # méthode attendue dans deferred_repo : create_if_not_exists(torrent_hash, name, can_be_deleted_at)
            created = self.deferred_deletion_repo.create_if_not_exists(torrent_hash=torrent_hash, name=name, can_be_deleted_at=can_be_deleted_at)
            if created:
                self.logger.info("migrate_deferred_torrent: deferred row created for hash=%s can_be=%s", torrent_hash, can_be_deleted_at)
            else:
                self.logger.debug("migrate_deferred_torrent: deferred row already exists for hash=%s", torrent_hash)
        except Exception:
            self.logger.exception("migrate_deferred_torrent: failed to create deferred row for hash=%s", torrent_hash)

        # remove Torrent row (best-effort)
        try:
            rows = self.torrent_repo.delete_by_hash(torrent_hash)
            if rows:
                self.logger.info("migrate_deferred_torrent: removed torrent row for hash=%s rows=%s", torrent_hash, rows)
            else:
                self.logger.debug("migrate_deferred_torrent: no torrent row removed for hash=%s", torrent_hash)
        except Exception:
            self.logger.exception("migrate_deferred_torrent: failed to delete torrent row for hash=%s", torrent_hash)

    
    # -----------------------------
    # Gotify helpers
    # ----------------------------- 
    def _send_notify(self,
                     movie_title: str,
                     old_torrent: Optional[str],
                     new_torrent: Optional[str],
                     deleted: Optional[list],
                     not_found: Optional[list],
                     failed: Optional[list],
                     image_url: Optional[str] = None) -> dict:
        
        deleted = deleted or []
        not_found = not_found or []
        failed = failed or []
        movie_title = movie_title or "unknown"

        title_map = {
            (True, False, False): "Webhook Cleaner : Nettoyage effectué",
            (False, True, False): "Webhook Cleaner : Nettoyage effectué",
            (True, True, False): "Webhook Cleaner : Nettoyage effectué",
            (False, False, True): "Webhook Cleaner : Nettoyage échoué",
            (True, False, True): "Webhook Cleaner : Nettoyage partiel",
            (False, True, True): "Webhook Cleaner : Nettoyage partiel",
            (True, True, True): "Webhook Cleaner : Nettoyage partiel",
            (False, False, False): "Webhook Cleaner : Ajout du torrent effectué"
        }
        title = title_map.get((bool(deleted), bool(not_found), bool(failed)), "Webhook Cleaner : État inconnu")

        lines: list[str] = []
        if old_torrent:
            lines.append(f"Old: {old_torrent}")
        if new_torrent:
            lines.append(f"New: {new_torrent}")
        if deleted:
            lines.append("Deleted: " + ", ".join(deleted))
        if not_found:
            lines.append("Not found: " + ", ".join(not_found))
        if failed:
            lines.append("Failed (not removed on qB): " + ", ".join(failed))
        if image_url:
            lines.append("Image: " + image_url)

        preview = (lines[0] + " | " + (lines[1] if len(lines) > 1 else ""))[:300] if lines else ""
        self.logger.info("[Gotify] title=%s preview=%s", title, preview)
        self.logger.debug("[Gotify] full message lines: %s", lines)

        return notify_gotify(title, lines, image_url=image_url)

    # -----------------------------
    # Torrent helpers
    # -----------------------------
    def ensure_torrent_exists(self, torrent_hash: str, name: Optional[str] = None):
        
        torrent = self.torrent_repo.get_by_hash(torrent_hash)
        if torrent:
            self.logger.debug("ensure_torrent_exists: existing torrent id=%s hash=%s", torrent.id, torrent.hash)
            return torrent

        self.logger.info("ensure_torrent_exists: creating torrent hash=%s name=%s", torrent_hash, name)
        # Get indexer name
        indexer = self.qb.get_indexer_from_hash(torrent_hash)
        torrent_created = self.torrent_repo.create(hashval=torrent_hash, name=name, indexer=indexer)
        return torrent_created
    
    def get_torrent_name_from_json(self, dto: dict) -> str | None:
        release = dto.get("torrent")
        source_path = release.get("sourcePath")
        if source_path:
            name_torrent = os.path.basename(source_path.rstrip("/\\"))
            return name_torrent
        return None