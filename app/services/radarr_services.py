# app/services/radarr_services.py
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

    def import_completed_movie(self, dto: dict) -> dict:
        # defensive parsing of dto
        torrent_dto = dto.get("torrent") or {}
        torrent_hash = torrent_dto.get("hash")
        if not torrent_hash:
            raise ValueError("torrent hash required")

        radarr_id = dto.get("radarr_id")
        title = dto.get("title")
        release_title = torrent_dto.get("releaseTitle")

        torrent = self.torrent_repo.get_by_hash(torrent_hash)
        if torrent is None:
            torrent = self.torrent_repo.create(hashval=torrent_hash, name=release_title)

        movie = None
        if radarr_id:
            movie = self.movie_repo.get_by_radarr_id(radarr_id)
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

    def _send_notify(self, case: str, movie_name: str, deleted_names: list, failed_names: list):
        deleted_names = deleted_names or []
        failed_names = failed_names or []
        movie_name = movie_name or "unknown"

        if case == "deleted":
            title = f"Suppression reussi : {movie_name}"
            body = ", ".join(deleted_names) if deleted_names else "aucun"
        elif case == "partial":
            title = f"Suppression partielle : {movie_name}"
            d = ", ".join(deleted_names) if deleted_names else "aucun"
            f = ", ".join(failed_names) if failed_names else "aucun"
            body = f"deleted: {d}; failed: {f}"
        else:  # failed
            title = f"Suppression echoué : {movie_name}"
            body = ", ".join(failed_names) if failed_names else "aucun"

        return notify_gotify(title, [body])

    def perform_qbittorrent_delete(self, old_torrent_id: int, hashes_to_delete: list, old_torrent_name: str, movie) -> dict:
        # call qB delete (delete_files=True)
        qb_result = self.qb.delete_torrents(hashes_to_delete, delete_files=True)

        # Log qB request/response
        self.logger.info("[qBittorrent] qB request payload: %s", qb_result.get("request"))
        self.logger.info("[qBittorrent] qB response payload: %s", qb_result.get("response") or qb_result.get("error"))

        deleted = qb_result.get("deleted", [])
        failed = qb_result.get("failed", [])
        absent = qb_result.get("absent", [])
        error = qb_result.get("error")

        # Determine status
        if deleted and not failed:
            status = "deleted"
        elif deleted and failed:
            status = "partial"
        else:
            status = "failed"

        return {
            "status": status,
            "qb_result": qb_result,
            "deleted": deleted,
            "failed": failed,
            "absent": absent,
            "error": error,
        }

    def perform_bdd_delete(self, deleted: list) -> dict:
        """
        Delete torrents rows in DB for the provided deleted list (list of (hash,name)).
        Returns dict: {"deleted_total": int, "deleted_hashes": [hash,...]}
        """
        deleted_total = 0
        deleted_hashes = []
        try:
            for h, _ in deleted:
                try:
                    deleted_rows = self.torrent_repo.delete_by_hash(h)
                    if deleted_rows:
                        deleted_total += 1
                        deleted_hashes.append(h)
                        self.logger.info("[BBDD] Deleted %d DB rows for hash %s", deleted_rows, h)
                    else:
                        # row existed not found or already removed
                        self.logger.info("[BBDD] No DB rows removed for hash %s (maybe already gone)", h)
                except Exception as e:
                    self.logger.exception("[BBDD] Failed to delete DB row for hash %s: %s", h, e)
            try:
                db.session.commit()
            except Exception:
                self.logger.exception("[BBDD] Commit failed after DB deletions; rolling back")
                try:
                    db.session.rollback()
                except Exception:
                    self.logger.exception("[BBDD] Rollback failed after commit error")
        except SQLAlchemyError:
            self.logger.exception("[BBDD] DB delete rows failed, rolling back")
            try:
                db.session.rollback()
            except Exception:
                self.logger.exception("[BBDD] Rollback failed after SQLAlchemyError")
        return {"deleted_total": deleted_total, "deleted_hashes": deleted_hashes}

    def handle_different(self, movie, new_torrent):
        old_torrent_id = movie.latest_torrent_id
        self.logger.info("handle_different: old_torrent_id=%s, new_torrent_id=%s", old_torrent_id, new_torrent.id)
        if not old_torrent_id:
            raise ValueError("handle_different called but movie has no latest_torrent_id")

        # update pointer to new torrent and commit
        movie.latest_torrent_id = new_torrent.id
        try:
            db.session.commit()
        except Exception:
            self.logger.exception("[BBDD] Failed to commit updated movie.latest_torrent_id; rolling back")
            try:
                db.session.rollback()
            except Exception:
                self.logger.exception("[BBDD] Rollback failed after commit error")

        # get old torrent (for name) and hashes to delete
        old_torrent = self.torrent_repo.get_by_id(old_torrent_id)
        old_torrent_name = getattr(old_torrent, "name", None)

        hashes_to_delete = self.torrent_repo.find_hashes_to_delete(old_torrent_id)
        if not hashes_to_delete:
            self.logger.error("[BBDD] No hashes found for old_torrent_id=%s", old_torrent_id)
            return {"action": "error", "message": "inconsistent_db_no_hashes", "movie_id": movie.id}

        # Ensure qB authenticated
        try:
            self.qb.login()
        except Exception as e:
            self.logger.exception("[qBittorrent] qB login failed: %s", e)
            self._send_notify("failed", movie.title or f"id:{movie.id}", [], [old_torrent_name] if old_torrent_name else [])
            return {"action": "error", "message": "failed_qb_login", "movie_id": movie.id, "error": str(e)}

        # perform qB delete (separated)
        qb_out = self.perform_qbittorrent_delete(old_torrent_id, hashes_to_delete, old_torrent_name, movie)
        status = qb_out["status"]
        deleted = qb_out["deleted"]   # list of (hash,name)
        failed = qb_out["failed"]     # list of (hash,name)

        # prepare name lists
        deleted_names = [n for (_, n) in deleted]
        failed_names = [n for (_, n) in failed]

        # If qB deleted some torrents -> reflect that in DB (only for those deleted)
        bdd_result = {"deleted_total": 0, "deleted_hashes": []}
        if deleted:
            bdd_result = self.perform_bdd_delete(deleted)

        # Log DB high-level status so it's easy to spot in logs
        total_deleted_qb = len(deleted)
        total_failed_qb = len(failed)
        if status == "deleted":
            # All were deleted by qB: ensure DB deleted count matches expectation
            if bdd_result["deleted_total"] == total_deleted_qb:
                self.logger.info("[BBDD] All qB-deleted hashes removed from DB (%d)", bdd_result["deleted_total"])
            else:
                # mismatch: some DB rows not found or other issue
                self.logger.warning("[BBDD] qB deleted %d hashes but DB removed %d rows", total_deleted_qb, bdd_result["deleted_total"])
        elif status == "partial":
            self.logger.warning("[BBDD] Partial qB delete: qb_deleted=%d qb_failed=%d; db_removed=%d",
                                total_deleted_qb, total_failed_qb, bdd_result["deleted_total"])
        else:  # failed
            # qB didn't delete anything: do not touch DB
            self.logger.info("[BBDD] qB deletion failed -> DB preserved for hashes: %s", ", ".join(hashes_to_delete))

        # notify depending on result
        if status == "deleted":
            self._send_notify("deleted", movie.title or f"id:{movie.id}", deleted_names, [])
        elif status == "partial":
            self._send_notify("partial", movie.title or f"id:{movie.id}", deleted_names, failed_names)
            return {"action": "error", "message": "partial_qb_delete", "movie_id": movie.id, "qb_result": qb_out}
        else:  # failed
            self._send_notify("failed", movie.title or f"id:{movie.id}", [], failed_names or ([old_torrent_name] if old_torrent_name else []))
            return {"action": "error", "message": "failed_qb_delete", "movie_id": movie.id, "qb_result": qb_out}

        return {
            "action": "replace",
            "movie_id": movie.id,
            "old_torrent_id": old_torrent_id,
            "new_torrent_id": new_torrent.id,
            "deleted_db_rows": bdd_result["deleted_total"],
            "qb_result": qb_out["qb_result"]
        }

    def handle_not_found(self, radarr_id, title, torrent):
        movie = self.movie_repo.create(radarr_id=radarr_id, title=title, latest_torrent_id=torrent.id)
        self.logger.info("[BBDD] movie created and linked to torrent (movie_id=%s, torrent_id=%s)", movie.id, torrent.id)
        return {"action": "create", "movie_id": movie.id, "torrent_id": torrent.id}
