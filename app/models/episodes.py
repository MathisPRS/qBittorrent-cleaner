from datetime import datetime
from sqlalchemy import UniqueConstraint, Index
from ..extensions import db

class Episodes(db.Model):
    __tablename__ = "episodes"
    __table_args__ = (
        UniqueConstraint("serie_id", "season", "episode", name="uq_episode_series_season_episode"),
        Index("ix_episode_series_season_episode", "serie_id", "season", "episode"),
    )

    id = db.Column(db.Integer, primary_key=True)
    serie_id = db.Column(
        db.Integer,
        db.ForeignKey("series.id", ondelete="SET NULL"),
        nullable=True,
    )

    title = db.Column(db.String(512), nullable=True)
    season = db.Column(db.Integer, nullable=False)
    episode = db.Column(db.Integer, nullable=False)

    latest_torrent_id = db.Column(
        db.Integer,
        db.ForeignKey("torrents.id", ondelete="SET NULL"),
        nullable=True
    )

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # relations
    series = db.relationship("Series", back_populates="episodes")
    latest_torrent = db.relationship("Torrents", foreign_keys=[latest_torrent_id])

    def __repr__(self):
        return (
            f"<Episode id={self.id} serie_id={self.serie_id} "
            f"S{self.season:02d}E{self.episode:02d} title={self.title!r}>"
        )
