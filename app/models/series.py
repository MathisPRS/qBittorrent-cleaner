from datetime import datetime
from sqlalchemy import UniqueConstraint
from ..extensions import db

class Series(db.Model):
    __tablename__ = "series"
    __table_args__ = (
        UniqueConstraint("sonarr_id", name="uq_series_sonarr_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    # on retire unique=True ici (contrainte déclarée dans __table_args__ avec un name)
    sonarr_id = db.Column(db.String(64), nullable=True)
    title = db.Column(db.String(512), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # relation vers les épisodes
    episodes = db.relationship(
        "Episodes",
        back_populates="series",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Episodes.season, Episodes.episode"
    )

    def __repr__(self):
        return f"<Series id={self.id} sonarr_id={self.sonarr_id} title={self.title!r}>"
