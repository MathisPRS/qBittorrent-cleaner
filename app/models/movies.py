from datetime import datetime
from sqlalchemy import UniqueConstraint
from ..extensions import db

class Movie(db.Model):
    __tablename__ = "movies"
    __table_args__ = (
        UniqueConstraint("radarr_id", name="uq_movies_radarr_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    radarr_id = db.Column(db.String(64), nullable=True)  # nullable True pour rester cohérent
    title = db.Column(db.String(512), nullable=True)
    latest_torrent_id = db.Column(
        db.Integer,
        db.ForeignKey("torrents.id", ondelete="SET NULL"),
        nullable=True
    )
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    latest_torrent = db.relationship("Torrents", foreign_keys=[latest_torrent_id])

    def __repr__(self):
        return f"<Movie id={self.id} radarr_id={self.radarr_id} title={self.title!r}>"
