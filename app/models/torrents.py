# app/models/torrents.py
from datetime import datetime
from ..extensions import db

class Torrents(db.Model):
    __tablename__ = "torrents"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(256), nullable=True)
    hash = db.Column(db.String(128), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    cross_seed_id = db.Column(db.Integer, db.ForeignKey("torrents.id", ondelete="SET NULL"))

    cross_seeds = db.relationship("Torrents", remote_side=[id], backref="parent_seed", passive_deletes=True)

    def __repr__(self):
        return f"<Torrent id={self.id} hash={self.hash}>"
