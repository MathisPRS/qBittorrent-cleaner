# app/repositories/series_repo.py
from ..extensions import db
from ..models.series import Series

class SeriesRepo:
    def get_by_sonarr_id(self, sonarr_id):
        if sonarr_id is None:
            return None
        return Series.query.filter_by(sonarr_id=str(sonarr_id)).first()

    def get_by_title(self, title):
        if not title:
            return None
        return Series.query.filter_by(title=title).first()

    def create(self, sonarr_id=None, title=None):
        s = Series(
            sonarr_id=str(sonarr_id) if sonarr_id is not None else None,
            title=title
        )
        db.session.add(s)
        try:
            db.session.commit()
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
            return self.get_by_sonarr_id(sonarr_id)
        return s

    def save(self, series):
        db.session.add(series)
        db.session.commit()
        return series
