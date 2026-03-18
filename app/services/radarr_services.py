# app/services/radarr_service.py
from typing import Dict, Optional
from .commun_services import CommunService
from app.services.deferred_deletions_services import DeferredDeletionService
from ..repositories.torrents_repo import TorrentsRepo
from ..repositories.movies_repo import MoviesRepo
from ..adapters.qbittorrent_adapter import QbittorrentAdapter
from ..extensions import db
from app.logger import get_logger


class RadarrService:

    def __init__(self, app):
        self.app = app
        self.logger = get_logger(__name__, app=app)
        self.torrents_repo = TorrentsRepo()
        self.movies_repo = MoviesRepo()
        self.commun_service = CommunService(app)
        self.deferred_deletion_services = DeferredDeletionService(app)
        self.qb = QbittorrentAdapter()


    def import_completed_movie(self, dto: Dict) -> Dict:
        torrent_dto = dto.get("torrent")
        torrent_hash = torrent_dto.get("hash")
        if not torrent_hash:
            raise ValueError("torrent hash required")

        radarr_id = dto.get("radarr_id")
        if not radarr_id:
            self.logger.warning(
                "import_completed_movie: no radarr_id — refusing to create orphan torrent/movie (hash=%s)",
                torrent_hash,
            )
            return {"action": "skipped", "reason": "no_radarr_id"}

        title = dto.get("title")
        movie_image_url = dto.get("image")
        new_torrent_name = self.commun_service.get_torrent_name_from_json(dto)
        # Ensure torrent exist
        torrent = self.commun_service.ensure_torrent_exists(torrent_hash, name=new_torrent_name)

        # find movie by radarr_id
        existing_movie = self.movies_repo.get_by_radarr_id(radarr_id) if radarr_id else None

        if existing_movie is None:
            return self.create_movie_and_link(radarr_id, title, torrent)

        return self.update_existing_movie(
            existing_movie, torrent, torrent_hash,
            new_torrent_name=new_torrent_name,
            movie_image_url=movie_image_url,
        )


    def create_movie_and_link(self, radarr_id: Optional[str], title: str, torrent) -> Dict:
        movie = self.movies_repo.create(radarr_id=radarr_id, title=title, latest_torrent_id=torrent.id)
        if not movie:
            self.logger.error("create_movie_and_link: failed to create movie (radarr_id=%s title=%s)", radarr_id, title)
            return {"action": "error", "message": "failed_create_movie"}

        self.logger.info("create_movie_and_link: created movie id=%s radarr_id=%s linked to torrent_id=%s", movie.id, radarr_id, torrent.id)
        self.logger.info("No deletion detected, no Gotify needed")

        return {"action": "created", "movie_id": movie.id, "torrent_id": torrent.id}


    def update_existing_movie(
        self,
        movie,
        new_torrent,
        torrent_hash: str,
        new_torrent_name: Optional[str] = None,
        movie_image_url: Optional[str] = None,
    ) -> Dict:
        # --- 1) fetch current hash & old torrent name for notifications (best-effort)
        current_hash = None
        old_torrent_name: Optional[str] = None
        if movie.latest_torrent_id:
            try:
                cur = self.torrents_repo.get_by_id(movie.latest_torrent_id)
                if cur:
                    current_hash = getattr(cur, "hash", None)
                    old_torrent_name = getattr(cur, "name", None)
            except Exception:
                self.logger.exception("update_existing_movie: failed to load current torrent by id=%s", movie.latest_torrent_id)

        # --- 2) if identical hash -> noop/ignored
        if current_hash and torrent_hash and current_hash.lower() == (torrent_hash or "").strip().lower():
            self.logger.info(
                "update_existing_movie: movie id=%s - received torrent matches current latest hash -> ignored",
                movie.id
            )
            return {"action": "ignored", "movie_id": movie.id, "torrent_id": new_torrent.id}

        # --- 3) if no previous torrent -> link and notify (no deletion work)
        if not movie.latest_torrent_id:
            return self.link_movie_without_previous_torrent(
                movie, new_torrent,
                old_torrent_name=old_torrent_name,
                new_torrent_name=new_torrent_name,
                movie_image_url=movie_image_url,
            )

        # --- 4) There is an old torrent -> switch pointer to new torrent (DB update via repo)
        old_torrent_id = movie.latest_torrent_id
        try:
            updated = self.movies_repo.update_latest_torrent_id(radarr_id=movie.radarr_id, latest_torrent_id=new_torrent.id)
            if not updated:
                self.logger.warning("update_existing_movie: update affected 0 rows (movie_id=%s)", movie.id)
        except Exception:
            self.logger.exception("update_existing_movie: DB commit failed when updating movie.latest_torrent_id")
            return {"action": "error", "message": "db_commit_failed", "movie_id": movie.id}

        # --- 5) collect candidate hashes to delete (old + cross-seeds)
        try:
            candidate_hashes = self.torrents_repo.get_hashes_to_delete(old_torrent_id)
        except Exception:
            self.logger.exception(
                "update_existing_movie: failed to collect hashes_to_delete for old_torrent_id=%s", old_torrent_id
            )
            return {"action": "error", "message": "failed_collect_hashes", "movie_id": movie.id}

        if not candidate_hashes:
            self.logger.error("update_existing_movie: no hashes found for old_torrent_id=%s", old_torrent_id)
            return {
                "action": "updated",
                "movie_id": movie.id,
                "new_torrent_id": new_torrent.id,
                "note": "no_hashes_found_for_old_torrent"
            }

        # --- 6) partition ready vs deferred: filter_deferred_deletion_hash enqueues deferred ones
        try:
            ready_to_be_deleted = self.deferred_deletion_services.filter_deferred_deletion_hash(candidate_hashes)
        except Exception:
            self.logger.exception("update_existing_movie: filter_deferred_deletion_hash failed")
            # conservative fallback: attempt to delete all candidate hashes
            ready_to_be_deleted = list(candidate_hashes)

        if not ready_to_be_deleted:
            # nothing ready now — everything deferred
            self.logger.info("update_existing_movie: no hashes ready for immediate deletion (all deferred for later cleanup)")

            try:
                self.commun_service._send_notify(
                    movie.title,
                    old_torrent_name or "—",
                    new_torrent_name,
                    deleted=[],
                    not_found=[],
                    failed=[],
                    image_url=movie_image_url
                )
            except Exception:
                self.logger.exception("update_existing_movie: notify failed (non-blocking)")

            return {
                "action": "updated",
                "movie_id": movie.id,
                "new_torrent_id": new_torrent.id,
                "note": "all_hashes_deferred"
            }

        # --- 7) delete ready hashes and notify (single helper)
        return self.delete_ready_hashes_and_notify(
            ready_to_be_deleted, movie, old_torrent_id, new_torrent,
            old_torrent_name=old_torrent_name,
            new_torrent_name=new_torrent_name,
            movie_image_url=movie_image_url,
        )


    def link_movie_without_previous_torrent(
        self,
        movie,
        new_torrent,
        old_torrent_name: Optional[str] = None,
        new_torrent_name: Optional[str] = None,
        movie_image_url: Optional[str] = None,
    ) -> Dict:
        try:
            updated = self.movies_repo.update_latest_torrent_id(movie.radarr_id, new_torrent.id)
            if not updated:
                self.logger.warning(
                    "link_movie_without_previous_torrent: update affected 0 rows (movie_id=%s)",
                    movie.id
                )

            self.logger.info(
                "link_movie_without_previous_torrent: linked movie id=%s to new torrent id=%s (no previous torrent)",
                movie.id, new_torrent.id
            )

        except Exception:
            self.logger.exception(
                "link_movie_without_previous_torrent: DB update failed (movie_id=%s)",
                movie.id
            )
            return {
                "action": "error",
                "message": "db_commit_failed",
                "movie_id": movie.id
            }

        try:
            self.commun_service._send_notify(
                movie.title,
                old_torrent_name or "—",
                new_torrent_name,
                deleted=[],
                not_found=[],
                failed=[],
                image_url=movie_image_url
            )
        except Exception:
            self.logger.exception("link_movie_without_previous_torrent: notify failed (non-blocking)")

        return {
            "action": "updated",
            "movie_id": movie.id,
            "new_torrent_id": new_torrent.id
        }


    def delete_ready_hashes_and_notify(
        self,
        ready_hashes: list,
        movie,
        old_torrent_id: Optional[int],
        new_torrent,
        old_torrent_name: Optional[str] = None,
        new_torrent_name: Optional[str] = None,
        movie_image_url: Optional[str] = None,
    ) -> Dict:

        result = self.commun_service.perform_deletion(ready_hashes)
        try:
            self.commun_service._send_notify(
                movie.title,
                old_torrent_name or "—",
                new_torrent_name,
                result["deleted_names"],
                result["absent_names"],
                result["failed_names"],
                movie_image_url
            )
        except Exception:
            self.logger.exception("delete_ready_hashes_and_notify: notify failed (non-blocking)")

        return {
            "action": "updated",
            "movie_id": movie.id,
            "old_torrent_id": old_torrent_id,
            "new_torrent_id": new_torrent.id,
            "deleted_db_rows": result["db_result"]["deleted_total"]
        }
