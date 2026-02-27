from ..extensions import db
from ..models.series import Series
from app.logger import get_logger

logger = get_logger(__name__)


class SeriesRepo:

    def get_by_sonarr_id(self, sonarr_id):
        if sonarr_id is None:
            return None
        try:
            return Series.query.filter_by(sonarr_id=str(sonarr_id)).first()
        except Exception:
            logger.exception("[BBDD] get_by_sonarr_id failed for sonarr_id=%s", sonarr_id)
            return None

    def get_by_title(self, title):
        if not title:
            return None
        try:
            return Series.query.filter_by(title=title).first()
        except Exception:
            logger.exception("[BBDD] get_by_title failed for title=%s", title)
            return None

    def create(self, sonarr_id=None, title=None):
        serie = Series(
            sonarr_id=str(sonarr_id) if sonarr_id is not None else None,
            title=title
        )

        db.session.add(serie)

        try:
            db.session.commit()
            logger.info(
                "[BBDD] Created Series id=%s sonarr_id=%s title=%s",serie.id, serie.sonarr_id, serie.title)
        except Exception:
            logger.exception(
                "[BBDD] create Series failed for sonarr_id=%s title=%s", sonarr_id, title)
            try:
                db.session.rollback()
            except Exception:
                logger.exception("[BBDD] rollback failed after create Series error")

            return self.get_by_sonarr_id(sonarr_id)

        return serie

    def save(self, series):
        try:
            db.session.add(series)
            db.session.commit()
            logger.info("[BBDD] Updated Series id=%s", series.id)
            return series
        except Exception:
            logger.exception("[BBDD] save failed for Series id=%s", getattr(series, "id", None))
            try:
                db.session.rollback()
            except Exception:
                logger.exception("[BBDD] rollback failed after save Series error")
            return None