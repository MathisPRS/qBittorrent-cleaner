from datetime import datetime
from sqlalchemy import JSON
from ..extensions import db

class Movie(db.Model):
    __tablename__ = "movies"

    id = db.Column(db.Integer, primary_key=True)
    radarr_id = db.Column(db.String(64), unique=True)
    title = db.Column(db.String(512))
    latest_torrent_id = db.Column(db.Integer, db.ForeignKey("torrents.id", ondelete="SET NULL"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    latest_torrent = db.relationship("Torrents")
