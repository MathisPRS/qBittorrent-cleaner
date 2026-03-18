from ..extensions import db
from ..models.episodes import Episodes
from app.logger import get_logger

logger = get_logger(__name__)


class EpisodesRepo:
    def get_by_series_season_episode(self, series_id: int, season: int, episode_number: int):
        if not series_id or season is None or episode_number is None:
            return None
        try:
            return Episodes.query.filter_by(
                serie_id=series_id,
                season=season,
                episode=episode_number
            ).first()
        except Exception:
            logger.exception("[BBDD] get_by_series_season_episode failed for serie_id=%s season=%s episode=%s",
                             series_id, season, episode_number)
            return None


    def get_by_id(self, episode_id):
        if not episode_id:
            return None
        try:
            return db.session.get(Episodes, episode_id)
        except Exception:
            logger.exception("[BBDD] get_by_id failed for episode_id=%s", episode_id)
            return None
        

    def create(self, serie_id: int, title: str, season: int, episode: int, latest_torrent_id: int = None):
        e = Episodes(
            serie_id=serie_id,
            title=title,
            season=season,
            episode=episode,
            latest_torrent_id=latest_torrent_id
        )
        db.session.add(e)
        try:
            db.session.commit()
            logger.info("[BBDD] Created Episode id=%s serie_id=%s S%02dE%02d", getattr(e, "id", None), serie_id, season, episode)
            return e
        except Exception:
            logger.exception("[BBDD] create Episode failed for serie_id=%s season=%s episode=%s", serie_id, season, episode)
            try:
                db.session.rollback()
            except Exception:
                logger.exception("[BBDD] rollback failed after create Episode error")
            # attempt to return existing one if race condition
            return self.get_by_series_season_episode(serie_id, season, episode)
        

    def save(self, episode: Episodes):
        try:
            db.session.add(episode)
            db.session.commit()
            logger.info("[BBDD] Saved Episode id=%s", getattr(episode, "id", None))
            return episode
        except Exception:
            logger.exception("[BBDD] save failed for Episode id=%s", getattr(episode, "id", None))
            try:
                db.session.rollback()
            except Exception:
                logger.exception("[BBDD] rollback failed after save Episode error")
            return None
        

    def update_latest_torrent_id(self, episode_id, latest_torrent_id):
        try:
            episode = self.get_by_id(episode_id)
            if not episode:
                logger.warning("[BBDD] update_latest_torrent_id: episode not found for id=%s", episode_id)
                return None

            episode.latest_torrent_id = latest_torrent_id
            db.session.add(episode)
            db.session.commit()

            logger.info("[BBDD] Updated Episode id=%s latest_torrent_id=%s", episode_id, latest_torrent_id)
            return episode

        except Exception:
            logger.exception("[BBDD] update_latest_torrent_id failed for episode_id=%s", episode_id)
            try:
                db.session.rollback()
            except Exception:
                logger.exception("[BBDD] rollback failed after update_latest_torrent_id error")
            return None