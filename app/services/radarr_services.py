# app/services/radarr_service.py
from typing import Dict, Optional
from ..services.commun_service import CommunService
from ..repositories.torrents_repo import TorrentsRepo
from ..repositories.movies_repo import MoviesRepo
from ..adapters.qbittorrent_adapter import QbittorrentAdapter
from ..extensions import db
from ..config import QBIT_HOST, QBIT_PASS, QBIT_USER
from app.logger import get_logger


class RadarrService:

    def __init__(self, app):
        self.app = app
        self.logger = get_logger(__name__, app=app)
        self.torrents_repo = TorrentsRepo()
        self.movies_repo = MoviesRepo()
        self.commun_service = CommunService(app)
        self.qb = QbittorrentAdapter()
        self._old_torrent_name: Optional[str] = None
        self._new_torrent_name: Optional[str] = None
        self._movie_image_url: Optional[str] = None
        self._new_torrent = None

    def import_completed_movie(self, dto: Dict) -> Dict:
        torrent_dto = dto.get("torrent") or {}
        torrent_hash = torrent_dto.get("hash")
        if not torrent_hash:
            raise ValueError("torrent hash required")

        radarr_id = dto.get("radarr_id")
        title = dto.get("title")
        self._movie_image_url = dto.get("image")
        self._new_torrent_name = self.commun_service.get_torrent_name_from_json(dto)
        # Ensure torrent exist
        torrent = self.commun_service.ensure_torrent_exists(torrent_hash, name=self._new_torrent_name)
        self._new_torrent = torrent

        # find movie by radarr_id (stored as string)
        existing_movie = self.movies_repo.get_by_radarr_id(radarr_id) if radarr_id else None

        if existing_movie is None:
            return self.create_movie_and_link(radarr_id, title, torrent)

        return self.update_existing_movie(existing_movie, torrent, torrent_hash)

    def create_movie_and_link(self, radarr_id: Optional[str], title: str, torrent) -> Dict:
        movie = self.movies_repo.create(radarr_id=radarr_id, title=title, latest_torrent_id=torrent.id)
        if not movie:
            self.logger.error("create_movie_and_link: failed to create movie (radarr_id=%s title=%s)", radarr_id, title)
            return {"action": "error", "message": "failed_create_movie"}

        self.logger.info("create_movie_and_link: created movie id=%s radarr_id=%s linked to torrent_id=%s", movie.id, radarr_id, torrent.id)
        self.logger.info("No deletion detected, no Gotify needed")

        return {"action": "created", "movie_id": movie.id, "torrent_id": torrent.id}

    def update_existing_movie(self, movie, new_torrent, torrent_hash: str) -> Dict:
        current_hash = None
        # if an old torrent id exists, fetch it to get its hash and name (for notifications)
        if movie.latest_torrent_id:
            cur = self.torrents_repo.get_by_id(movie.latest_torrent_id)
            if cur:
                current_hash = getattr(cur, "hash", None)
                self._old_torrent_name = getattr(cur, "name", None)

        # Normalize for comparison (if both present)
        if current_hash and torrent_hash and current_hash.lower() == torrent_hash.strip().lower():
            self.logger.info("update_existing_movie: movie id=%s - received torrent matches current latest hash -> ignored", movie.id)
            return {"action": "ignored", "movie_id": movie.id, "torrent_id": new_torrent.id}

        # if no previous torrent -> link and commit (no deletion)
        if not movie.latest_torrent_id:
            try:
                if hasattr(self.movies_repo, "update_latest_torrent_id"):
                    self.movies_repo.update_latest_torrent_id(movie.radarr_id, new_torrent.id)
                else:
                    movie.latest_torrent_id = new_torrent.id
                    db.session.add(movie)
                    db.session.commit()
                self.logger.info("update_existing_movie: linked movie id=%s to new torrent id=%s (no previous torrent)", movie.id, new_torrent.id)
            except Exception:
                self.logger.exception("update_existing_movie: DB commit failed while linking new torrent (no previous torrent)")
                try:
                    db.session.rollback()
                except Exception:
                    self.logger.exception("update_existing_movie: rollback failed after commit error")
                return {"action": "error", "message": "db_commit_failed", "movie_id": movie.id}

            # lightweight notification (non-blocking)
            try:
                self.commun_service._send_notify(
                    movie.title,
                    self._old_torrent_name or "—",
                    self._new_torrent_name,
                    deleted=[],
                    not_found=[],
                    failed=[],
                    image_url=self._movie_image_url
                )
            except Exception:
                self.logger.exception("update_existing_movie: notify failed (non-blocking)")

            return {"action": "updated", "movie_id": movie.id, "new_torrent_id": new_torrent.id}

        old_torrent_id = movie.latest_torrent_id

        # Update movie to point to new torrent first (keeping DB consistent)
        try:
            movie.latest_torrent_id = new_torrent.id
            db.session.add(movie)
            db.session.commit()
        except Exception:
            self.logger.exception("update_existing_movie: DB commit failed when updating movie.latest_torrent_id")
            try:
                db.session.rollback()
            except Exception:
                self.logger.exception("update_existing_movie: rollback failed after commit error")
            return {"action": "error", "message": "db_commit_failed", "movie_id": movie.id}

        # Collect hashes to delete (old + cross-seeds)
        try:
            hashes_to_delete = self.torrents_repo.find_hashes_to_delete(old_torrent_id)
        except Exception:
            self.logger.exception("update_existing_movie: failed to collect hashes_to_delete for old_torrent_id=%s", old_torrent_id)
            return {"action": "error", "message": "failed_collect_hashes", "movie_id": movie.id}

        if not hashes_to_delete:
            self.logger.error("update_existing_movie: no hashes found for old_torrent_id=%s", old_torrent_id)
            return {"action": "updated", "movie_id": movie.id, "new_torrent_id": new_torrent.id, "note": "no_hashes_found_for_old_torrent"}

        # Delete from qBittorrent and gather results
        qb_out = self.commun_service.perform_qbittorrent_delete(hashes_to_delete) or {}
        deleted = qb_out.get("deleted", [])
        failed = qb_out.get("failed", [])
        absent = qb_out.get("absent", [])
        hashes_for_db = qb_out.get("hashes_to_delete_in_db", [])

        # Delete old torrent(s) from DB
        try:
            db_result = self.commun_service.perform_bdd_delete(hashes_for_db)
        except Exception:
            self.logger.exception("update_existing_movie: perform_bdd_delete failed")
            db_result = {"deleted_total": 0}

        # prepare notification lists
        deleted_names = [n for (_h, n) in deleted if n]
        absent_names = list(absent) if absent else []
        failed_names = [n for (_h, n) in failed if n]

        try:
            self.commun_service._send_notify(
                movie.title,
                self._old_torrent_name or "—",
                self._new_torrent_name,
                deleted_names,
                absent_names,
                failed_names,
                self._movie_image_url
            )
        except Exception:
            self.logger.exception("update_existing_movie: notify failed (non-blocking)")

        return {
            "action": "updated",
            "movie_id": movie.id,
            "old_torrent_id": old_torrent_id,
            "new_torrent_id": new_torrent.id,
            "deleted_db_rows": db_result.get("deleted_total", 0)
        }