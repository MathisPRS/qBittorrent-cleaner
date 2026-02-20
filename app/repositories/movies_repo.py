# app/repositories/movie_repo.py
from ..extensions import db
from ..models.movies import Movie

class MoviesRepo:
    def get_by_radarr_id(self, radarr_id):
        if not radarr_id:
            return None
        return Movie.query.filter_by(radarr_id=str(radarr_id)).first()

    def get_by_title(self, title):
        if not title:
            return None
        return Movie.query.filter_by(title=title).first()
    
    def update_latest_torrent_id(self, radarr_id, latest_torrent_id):
        movie = self.get_by_radarr_id(radarr_id)
        if not movie:
            return None
        movie.latest_torrent_id = latest_torrent_id
        db.session.add(movie)
        db.session.commit()
        return movie

    def create(self, radarr_id=None, title=None, latest_torrent_id=None):
        m = Movie(
            radarr_id=str(radarr_id) if radarr_id is not None else None,
            title=title,
            latest_torrent_id=latest_torrent_id
        )
        db.session.add(m)
        db.session.commit()
        return m

    def save(self, movie):
        db.session.add(movie)
        db.session.commit()
        return movie
