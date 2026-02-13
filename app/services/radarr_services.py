# app/services/radarr_services.py
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
        self.torrent_repo = TorrentsRepo()
        self.movie_repo = MoviesRepo()
        self.qb = QbittorrentAdapter(QBIT_HOST, QBIT_USER, QBIT_PASS, logger=self.logger)

    def import_completed_movie(self, dto: dict) -> dict:
        torrent_hash = dto.get("torrent").get("hash")
        if not torrent_hash:
            raise ValueError("torrent hash required")

        radarr_id = dto.get("radarr_id")
        title = dto.get("title")
        release_title = dto.get("torrent").get("releaseTitle")
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

    def handle_different(self, movie, new_torrent):
        old_torrent_id = movie.latest_torrent_id
        self.logger.debug("handle_different: old_torrent_id=%s, new_torrent_id=%s", old_torrent_id, new_torrent.id)
        if not old_torrent_id:
            raise ValueError("handle_different called but movie has no latest_torrent_id")
        movie.latest_torrent_id = new_torrent.id
        try:
            db.session.commit(movie)
        except Exception:
            pass

        hashes_to_delete = self.torrent_repo.find_cross_seed_hashes(old_torrent_id)
        if not hashes_to_delete:
            self.logger.error("No hashes found for old_torrent_id=%s", old_torrent_id)
            return {"action": "error", "message": "inconsistent_db_no_hashes", "movie_id": movie.id}

        try:
            self.qb.login()
            qb_result = self.qb.delete_torrents(hashes_to_delete, delete_files=False)
            self.logger.info("qB delete requested for %s -> %s", hashes_to_delete, qb_result)
        except Exception as e:
            self.logger.exception("qB delete failed for hashes %s: %s", hashes_to_delete, e)
            return {"action": "error", "message": "failed_qb_delete", "movie_id": movie.id, "error": str(e)}

        deleted_total = 0
        for h in hashes_to_delete:
            try:
                deleted = self.torrent_repo.delete_by_hash(h)
                deleted_total += (1 if deleted else 0)
            except Exception as e:
                self.logger.exception("Failed to delete DB row for hash %s: %s", h, e)

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
        self.logger.info("movie created and linked to torrent (movie_id=%s, torrent_id=%s)", movie.id, torrent.id)
        return {"action": "create", "movie_id": movie.id, "torrent_id": torrent.id}
