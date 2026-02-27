from ..extensions import db
from ..models.movies import Movie
from app.logger import get_logger

logger = get_logger(__name__)

class MoviesRepo:

    def get_by_radarr_id(self, radarr_id):
        if not radarr_id:
            return None
        try:
            return Movie.query.filter_by(radarr_id=str(radarr_id)).first()
        except Exception:
            logger.exception("[BBDD] get_by_radarr_id failed for radarr_id=%s", radarr_id)
            return None
        

    def get_by_title(self, title):
        if not title:
            return None
        try:
            return Movie.query.filter_by(title=title).first()
        except Exception:
            logger.exception("[BBDD] get_by_title failed for title=%s", title)
            return None
            
    
    def update_latest_torrent_id(self, radarr_id, latest_torrent_id):
        try:
            movie = self.get_by_radarr_id(radarr_id)
            if not movie:
                logger.warning(
                    "[BBDD] update_latest_torrent_id: movie not found for radarr_id=%s",
                    radarr_id
                )
                return None

            movie.latest_torrent_id = latest_torrent_id
            db.session.add(movie)
            db.session.commit()

            logger.info(
                "[BBDD] Updated Movie id=%s latest_torrent_id=%s",
                movie.id,
                latest_torrent_id
            )

            return movie

        except Exception:
            logger.exception(
                "[BBDD] update_latest_torrent_id failed for radarr_id=%s",
                radarr_id
            )
            try:
                db.session.rollback()
            except Exception:
                logger.exception("[BBDD] rollback failed after update_latest_torrent_id error")
            return None
        

    def create(self, radarr_id=None, title=None, latest_torrent_id=None):
        movie = Movie(
            radarr_id=str(radarr_id) if radarr_id is not None else None,
            title=title,
            latest_torrent_id=latest_torrent_id
        )

        try:
            db.session.add(movie)
            db.session.commit()
            logger.info(
                "[BBDD] Created Movie id=%s radarr_id=%s title=%s",
                movie.id,
                movie.radarr_id,
                movie.title
            )

            return movie

        except Exception:
            logger.exception(
                "[BBDD] create Movie failed for radarr_id=%s title=%s",
                radarr_id,
                title
            )
            try:
                db.session.rollback()
            except Exception:
                logger.exception("[BBDD] rollback failed after create Movie error")

            # tentative récupération si race condition
            return self.get_by_radarr_id(radarr_id)
        

    def save(self, movie):
        try:
            db.session.add(movie)
            db.session.commit()

            logger.info("[BBDD] Saved Movie id=%s", movie.id)
            return movie

        except Exception:
            logger.exception("[BBDD] save failed for Movie id=%s", getattr(movie, "id", None))
            try:
                db.session.rollback()
            except Exception:
                logger.exception("[BBDD] rollback failed after save Movie error")
            return None