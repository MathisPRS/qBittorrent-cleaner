import os
from typing import Optional
from ..repositories.torrents_repo import TorrentsRepo
from ..repositories.movies_repo import MoviesRepo
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
        self.qb = QbittorrentAdapter(QBIT_HOST, QBIT_USER, QBIT_PASS, logger_obj=self.logger)

    # -----------------------------
    # qBittorrent helpers
    # -----------------------------
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

    # -----------------------------
    # BDD helpers
    # -----------------------------

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
    # Gotify helpers
    # -----------------------------
    def _send_notify(self,
                 movie_title: str,
                 old_torrent: str | None,
                 new_torrent: str | None,
                 deleted: list,
                 not_found: list,
                 failed: list,
                 image_url: str | None = None) -> dict:
      
        # normaliser listes
        deleted = deleted or []
        not_found = not_found or []
        failed = failed or []
        movie_title = movie_title or "unknown"

        # titre selon le résultat
        title_map = {
            (True, False, False): "Webhook Cleaner : Nettoyage effectué",
            (False, True, False): "Webhook Cleaner : Nettoyage effectué",
            (True, True, False): "Webhook Cleaner : Nettoyage effectué",
            (False, False, True): "Webhook Cleaner : Nettoyage échoué",
            (True, False, True): "Webhook Cleaner : Nettoyage partiel",
            (False, True, True): "Webhook Cleaner : Nettoyage partiel",
            (True, True, True): "Webhook Cleaner : Nettoyage partiel",
        }
        title = title_map.get((bool(deleted), bool(not_found), bool(failed)), "Webhook Cleaner : État inconnu")

        # construire le corps du message
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

        # Garder l'URL en texte pour fallback / logs (optionnel)
        if image_url:
            # n'écrase pas l'attachment: l'adapter se chargera d'uploader le binaire
            lines.append("Image: " + image_url)

        # logs
        preview = (lines[0] + " | " + (lines[1] if len(lines) > 1 else ""))[:300] if lines else ""
        self.logger.info("[Gotify] title=%s preview=%s", title, preview)
        self.logger.debug("[Gotify] full message lines: %s", lines)

        # envoie
        return notify_gotify(title, lines, image_url=image_url)

    # -----------------------------
    # Torrent helpers
    # -----------------------------
    def ensure_torrent_exists(self, torrent_hash: str, name: Optional[str] = None):
        """
        Ensure a Torrents DB row exists for hash. Return the Torrents instance.
        """
        torrent = self.torrent_repo.get_by_hash(torrent_hash)
        if torrent:
            self.logger.debug("ensure_torrent_exists: existing torrent id=%s hash=%s", torrent.id, torrent.hash)
            return torrent

        self.logger.info("ensure_torrent_exists: creating torrent hash=%s name=%s", torrent_hash, name)
        return self.torrent_repo.create(hashval=torrent_hash, name=name)
    
    def get_torrent_name(self, dto: dict) -> str | None:
        release = dto.get("torrent")
        source_path = release.get("sourcePath")
        if source_path:
            name_torrent = os.path.basename(source_path.rstrip("/\\"))
            return name_torrent
        return None