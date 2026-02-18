from  ..services.commun_service import CommunService
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
        self.commun_service = CommunService(app)
        self.qb = QbittorrentAdapter(QBIT_HOST, QBIT_USER, QBIT_PASS, logger_obj=self.logger)
        self.old_torrent_name = str
        self.new_torrent_name = str
        self.movie_image_url = str


    def import_completed_movie(self, dto: dict) -> dict:
        # defensive parsing of dto
        torrent_dto = dto.get("torrent") or {}
        torrent_hash = torrent_dto.get("hash")
        if not torrent_hash:
            raise ValueError("torrent hash required")

        radarr_id = dto.get("radarr_id")
        title = dto.get("title")
        release_title = torrent_dto.get("releaseTitle")
        self.movie_image_url = dto.get("image")
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
        qb_out = self.commun_service.perform_qbittorrent_delete(hashes_to_delete)

        deleted = qb_out["deleted"]
        failed = qb_out["failed"]
        absent = qb_out["absent"]
        hashes_for_db = qb_out["hashes_to_delete_in_db"]

        # BDD delete hashes
        bdd_result = self.commun_service.perform_bdd_delete(hashes_for_db)

        # Gotify notification
        deleted_names = [n for (_h, n) in deleted if n]
        absent_names = list(absent) if absent else []
        failed_names = [n for (_h, n) in failed if n]

        # single call to the new notifier (non-intrusif, non-redondant)
        self.commun_service._send_notify(movie.title,
                        self.old_torrent_name,
                        self.new_torrent_name,
                        deleted_names,
                        absent_names,
                        failed_names,
                        self.movie_image_url)


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
