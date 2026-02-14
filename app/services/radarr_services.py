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

    def _notify_case(self, case: str, movie_name: str, torrent_name: str):
        if case == "success":
            title = f"Suppression reussi : {movie_name}"
            body = torrent_name or ""
        elif case == "partial":
            title = f"Suppression partielle : {movie_name}"
            body = torrent_name or ""
        else:  # error
            title = f"Suppression echoué : {movie_name}"
            body = torrent_name or ""
        # send single-line body (list with one string) as requested
        notify_gotify(title, [body])

    def handle_different(self, movie, new_torrent):
        old_torrent_id = movie.latest_torrent_id
        self.logger.debug("handle_different: old_torrent_id=%s, new_torrent_id=%s", old_torrent_id, new_torrent.id)
        if not old_torrent_id:
            raise ValueError("handle_different called but movie has no latest_torrent_id")
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
        old_torrent_name = getattr(old_torrent, "name", None) if old_torrent else None

        hashes_to_delete = self.torrent_repo.find_cross_seed_hashes(old_torrent_id)
        if not hashes_to_delete:
            self.logger.error("[BBDD] No hashes found for old_torrent_id=%s", old_torrent_id)
            return {"action": "error", "message": "inconsistent_db_no_hashes", "movie_id": movie.id}

        # Ensure qB authenticated
        try:
            self.qb.login()
        except Exception as e:
            self.logger.exception("[qBittorrent] qB login failed: %s", e)
            # single-line notify: title + second line = attempted torrent name (old torrent)
            self._notify_case("error", movie.title or f"id:{movie.id}", old_torrent_name or ",".join(hashes_to_delete))
            return {"action": "error", "message": "failed_qb_login", "movie_id": movie.id, "error": str(e)}

        # call qB delete (delete_files=True)
        qb_result = self.qb.delete_torrents(hashes_to_delete, delete_files=True)

        # Log qB request/response
        self.logger.debug("[qBittorrent] qB request payload: %s", qb_result.get("request"))
        self.logger.debug("[qBittorrent] qB response payload: %s", qb_result.get("response") or qb_result.get("error"))

        deleted = qb_result.get("deleted", [])
        failed = qb_result.get("failed", [])
        absent = qb_result.get("absent", [])
        error = qb_result.get("error")

        # Decide outcome and notify with single title + one body line (torrent name)
        # Use old_torrent_name as the body line if available else fallback to first deleted name or hashes list
        body_name = old_torrent_name or (deleted[0][1] if deleted else (failed[0][1] if failed else ",".join(hashes_to_delete)))

        if deleted and not failed:
            # success
            self._notify_case("success", movie.title or f"id:{movie.id}", body_name)
        elif deleted and failed:
            # partial
            self._notify_case("partial", movie.title or f"id:{movie.id}", body_name)
            return {"action": "error", "message": "partial_qb_delete", "movie_id": movie.id, "qb_result": qb_result}
        else:
            # nothing deleted or error
            self._notify_case("error", movie.title or f"id:{movie.id}", body_name)
            return {"action": "error", "message": "failed_qb_delete", "movie_id": movie.id, "qb_result": qb_result}

        # On success remove DB rows for deleted hashes (transactional)
        deleted_total = 0
        try:
            for h, _ in deleted:
                try:
                    deleted_rows = self.torrent_repo.delete_by_hash(h)
                    self.logger.info("[BBDD] Deleted %d DB rows for hash %s", deleted_rows, h)
                    deleted_total += (1 if deleted_rows else 0)
                except Exception as e:
                    self.logger.exception("[BBDD] Failed to delete DB row for hash %s: %s", h, e)
            try:
                db.session.commit()
            except Exception:
                self.logger.exception("[BBDD] Commit failed after DB deletions; rolling back")
                db.session.rollback()
        except SQLAlchemyError:
            self.logger.exception("[BBDD] DB delete rows failed, rolling back")
            db.session.rollback()

        return {
            "action": "replace",
            "movie_id": movie.id,
            "old_torrent_id": old_torrent_id,
            "new_torrent_id": new_torrent.id,
            "deleted_db_rows": deleted_total,
            "qb_result": qb_result
        }

    def handle_not_found(self, radarr_id, title, torrent):
        movie = self.movie_repo.create(radarr_id=radarr_id, title=title, latest_torrent_id=torrent.id)
        self.logger.info("[BBDD] movie created and linked to torrent (movie_id=%s, torrent_id=%s)", movie.id, torrent.id)
        return {"action": "create", "movie_id": movie.id, "torrent_id": torrent.id}
