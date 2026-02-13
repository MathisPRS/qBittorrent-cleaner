# app/services/radarr_service.py
from ..repositories.torrents_repo import TorrentsRepo
from ..repositories.movies_repo import MoviesRepo
from sqlalchemy.exc import IntegrityError

class RadarrService:
    def __init__(self, app):
        self.app = app
        self.torrent_repo = TorrentsRepo()
        self.movie_repo = MoviesRepo()

    def import_completed_movie(self, dto: dict) -> dict:
       
        torrent_data = dto.get("torrent", {})
        hashval = torrent_data.get("hash")
        print("Importing movie with torrent hash:", hashval)  # for debugging
        
        # 1) create torrent entry (allow hash None as placeholder)
        try:
            torrent = self.torrent_repo.create(hash=hashval)
        except IntegrityError:
            # hash unique constraint: if already exists, fetch existing row
            self.app.logger.debug("Torrent with hash already exists: %s", hashval)
            torrent = self.torrent_repo.get_by_hash(hashval)

        torrent_id = torrent.id if torrent else None

        # 2) check existing movie
        radarr_id = dto.get("radarr_id")
        title = dto.get("title")

        movie = None
        if radarr_id:
            movie = self.movie_repo.get_by_radarr_id(radarr_id)
        if not movie and title:
            movie = self.movie_repo.get_by_title(title)

        # 3) create movie if missing, attach latest_torrent_id
        created = False
        if not movie:
            movie = self.movie_repo.create(radarr_id=radarr_id, title=title, latest_torrent_id=torrent_id)
            created = True
        else:
            # Optionally update latest_torrent_id if not set
            if torrent_id and movie.latest_torrent_id != torrent_id:
                movie.latest_torrent_id = torrent_id
                self.movie_repo.save(movie)

        return {
            "movie_id": movie.id,
            "movie_created": created,
            "torrent_id": torrent_id,
            "torrent_hash": hashval
        }
