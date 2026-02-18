from ..repositories.torrents_repo import TorrentsRepo
from ..repositories.movies_repo import MoviesRepo
from ..adapters.qbittorrent_adapter import QbittorrentAdapter
from ..adapters.gotify_adapter import notify_gotify
from ..extensions import db

from ..config import QBIT_HOST, QBIT_PASS, QBIT_USER
from app.logger import get_logger
from sqlalchemy.exc import SQLAlchemyError


class RadarrService:
    def __init__(self, app):
        self.app = app
        self.logger = get_logger(__name__, app=app)
        self.torrent_repo = TorrentsRepo()
        self.movie_repo = MoviesRepo()
        # Ici on souhaite supprimer complètement les contenus locaux -> delete_files=True
        self.qb = QbittorrentAdapter(QBIT_HOST, QBIT_USER, QBIT_PASS, logger_obj=self.logger)
        self.old_torrent_name = str
        self.new_torrent_name = str
        self.movie_image = str

        

    def import_completed_movie(self, dto: dict) -> dict:
        # defensive parsing of dto
        torrent_dto = dto.get("torrent") or {}
        torrent_hash = torrent_dto.get("hash")
        if not torrent_hash:
            raise ValueError("torrent hash required")

        radarr_id = dto.get("radarr_id")
        title = dto.get("title")
        release_title = torrent_dto.get("releaseTitle")
        self.movie_image = dto.get("image")
        self.new_torrent_name = release_title

        torrent = self.torrent_repo.get_by_hash(torrent_hash)
        if torrent is None:
            torrent = self.torrent_repo.create(hashval=torrent_hash, name=release_title)

        movie = None
        if radarr_id:
            movie = self.movie_repo.get_by_radarr_id(radarr_id)
            self.old_torrent_name = movie.latest_torrent.name
        if movie is None:
            case = "not_found"
        else:
            current_hash = None
            if movie.latest_torrent_id:
                cur = self.torrent_repo.get_by_id(movie.latest_torrent_id)
                if cur:
                    current_hash = getattr(cur, "hash", None)
            case = "same" if (current_hash and current_hash.lower() == torrent_hash.lower()) else "different"

        handlers = {
            "same": lambda: self.handle_same(movie, torrent_hash, torrent),
            "different": lambda: self.handle_different(movie, torrent),
            "not_found": lambda: self.handle_not_found(radarr_id, title, torrent)
        }

        return handlers[case]()

    def handle_same(self, movie, hashval, torrent):
        msg = "latest torrent déjà connu"
        self.logger.info("%s (movie_id=%s, hash=%s)", msg, movie.id, hashval)
        return {"action": "noop", "message": msg, "movie_id": movie.id, "torrent_id": torrent.id}

    def _send_notify(self,
                 movie_title: str,
                 old_torrent_name: str | None,
                 new_torrent_name: str | None,
                 deleted_names: list,
                 absent_names: list,
                 failed_names: list,
                 image_url: str | None = None) -> dict:
        
        # normalise listes (évite None)
        deleted_names = deleted_names or []
        absent_names = absent_names or []
        failed_names = failed_names or []
        movie_title = movie_title or "unknown"

        # flags
        has_deleted = bool(deleted_names)
        has_absent = bool(absent_names)
        has_failed = bool(failed_names)

        # mapping tuple -> title (compact, évite if/elif multiples)
        title_map = {
            (True, False, False): "Webhook Cleaner : Nettoyage effectué",        # only deleted
            (False, True, False): "Webhook Cleaner : Nettoyage effectué",       # only absent
            (True, True, False): "Webhook Cleaner : Nettoyage effectué",        # deleted + absent
            (False, False, True): "Webhook Cleaner : Nettoyage échoué",         # only failed
            (True, False, True): "Webhook Cleaner : Nettoyage partiel",         # deleted + failed
            (False, True, True): "Webhook Cleaner : Nettoyage partiel",         # absent + failed
            (True, True, True): "Webhook Cleaner : Nettoyage partiel",          # all three
        }

        title = title_map.get((has_deleted, has_absent, has_failed), "Webhook Cleaner : État inconnu")

        # Compose message lines (compact, non-redondant)
        lines = []
        lines.append(f"Film: {movie_title}")

        if old_torrent_name:
            lines.append(f"Torrent supprimé : {old_torrent_name}")
        if new_torrent_name:
            lines.append(f"Torrent de remplacement : {new_torrent_name}")

        if deleted_names:
            lines.append("Torrents supprimés: " + ", ".join(deleted_names))
        if absent_names:
            lines.append("Torrents absents (déjà non présents sur qB): " + ", ".join(absent_names))
        if failed_names:
            lines.append("Torrents échoués (non supprimés sur qB): " + ", ".join(failed_names))

        if image_url:
            lines.append(f"Image: {image_url}")

        # logs : preview + debug complet
        preview = (lines[0] + " | " + (lines[1] if len(lines) > 1 else ""))[:300]
        self.logger.info("[Gotify] title=%s preview=%s", title, preview)
        self.logger.debug("[Gotify] full message lines: %s", lines)

        return notify_gotify(title, lines)

    def perform_qbittorrent_delete(self, hashes_to_delete: list) -> dict:

        qb_result = self.qb.delete_torrents(hashes_to_delete, delete_files=True)

        deleted = qb_result.get("deleted", []) or []
        failed = qb_result.get("failed", []) or []
        absent = qb_result.get("absent", []) or []

        deleted_hashes = [hash_value for (hash_value, _name) in deleted]
        hashes_to_delete_in_db = deleted_hashes + absent

        # Logs clairs et utiles
        if deleted_hashes:
            self.logger.info("[qBittorrent] deleted hashes: %s", ", ".join(deleted_hashes))

        if absent:
            self.logger.info("[qBittorrent] absent hashes: %s", ", ".join(absent))

        if failed:
            failed_hashes = [hash_value for (hash_value, _name) in failed]
            self.logger.warning("[qBittorrent] failed hashes: %s", ", ".join(failed_hashes))

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


    def handle_different(self, movie, new_torrent):
        old_torrent_id = movie.latest_torrent_id
        self.logger.info(
            "handle_different: old_torrent_id=%s, new_torrent_id=%s",
            old_torrent_id,
            new_torrent.id
        )

        if not old_torrent_id:
            raise ValueError("handle_different called but movie has no latest_torrent_id")

        # Update Movies with new torrent
        movie.latest_torrent_id = new_torrent.id
        try:
            db.session.commit()
        except Exception:
            self.logger.exception("[BBDD] Failed to commit movie update")
            db.session.rollback()

        # Get hashes to delete (old + cross-seeds)
        hashes_to_delete = self.torrent_repo.find_hashes_to_delete(old_torrent_id)

        if not hashes_to_delete:
            self.logger.error("[BBDD] No hashes found for old_torrent_id=%s", old_torrent_id)
            return {
                "action": "error",
                "message": "inconsistent_db_no_hashes",
                "movie_id": movie.id
            }

        # qBittorrent delete (with files) + get results
        qb_out = self.perform_qbittorrent_delete(hashes_to_delete)

        deleted = qb_out["deleted"]
        failed = qb_out["failed"]
        absent = qb_out["absent"]
        hashes_for_db = qb_out["hashes_to_delete_in_db"]

        # BDD delete hashes
        bdd_result = self.perform_bdd_delete(hashes_for_db)

        # Gotify notification
        deleted_names = [n for (_h, n) in deleted if n]
        absent_names = list(absent) if absent else []
        failed_names = [n for (_h, n) in failed if n]

        # single call to the new notifier (non-intrusif, non-redondant)
        self._send_notify(movie.title,
                        self.old_torrent_name,
                        self.new_torrent_name,
                        deleted_names,
                        absent_names,
                        failed_names,
                        self.movie_image)


        return {
            "action": "replace",
            "movie_id": movie.id,
            "old_torrent_id": old_torrent_id,
            "new_torrent_id": new_torrent.id,
            "deleted_db_rows": bdd_result["deleted_total"]
        }

    def handle_not_found(self, radarr_id, title, torrent):
        movie = self.movie_repo.create(radarr_id=radarr_id, title=title, latest_torrent_id=torrent.id)
        self.logger.info("[BBDD] movie created and linked to torrent (movie_id=%s, torrent_id=%s)", movie.id, torrent.id)
        return {"action": "create", "movie_id": movie.id, "torrent_id": torrent.id}
