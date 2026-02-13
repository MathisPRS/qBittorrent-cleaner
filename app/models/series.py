from datetime import datetime
from sqlalchemy import JSON
from ..extensions import db

class Series(db.Model):
    __tablename__ = "series"

    id = db.Column(db.Integer, primary_key=True)

    sonarr_id = db.Column(db.String(64))     # id de la série
    title = db.Column(db.String(512))

    season = db.Column(db.Integer, nullable=False)
    episode = db.Column(db.Integer, nullable=False)

    latest_torrent_id = db.Column(db.Integer, db.ForeignKey("torrents.id", ondelete="SET NULL"))
    cross_seed_ids = db.Column(JSON, default=list)

    is_pack = db.Column(db.Boolean, default=False)  # provient d’un season pack ?

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    latest_torrent = db.relationship("Torrents")

    __table_args__ = (
        db.UniqueConstraint("sonarr_id", "season", "episode", name="uix_series_episode"),
    )
