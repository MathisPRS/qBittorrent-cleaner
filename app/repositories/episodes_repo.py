# app/repositories/episodes_repo.py
from ..extensions import db
from ..models.episodes import Episodes

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
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
            # attempt to return existing one if race
            return self.get_by_series_season_episode(serie_id, season, episode)
        return e

    def save(self, episode: Episodes):
        db.session.add(episode)
        db.session.commit()
        return episode
