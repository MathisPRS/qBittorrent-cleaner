from datetime import datetime
from sqlalchemy import UniqueConstraint
from ..extensions import db

class Torrents(db.Model):
    __tablename__ = "torrents"
    __table_args__ = (
        UniqueConstraint("hash", name="uq_torrents_hash"),
    )

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(256), nullable=True)
    # on retire unique=True ici et on déclare la contrainte nommée plus haut
    hash = db.Column(db.String(128), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    indexer = db.Column(db.String(128), nullable=True)

    cross_seed_id = db.Column(
        db.Integer,
        db.ForeignKey("torrents.id", ondelete="CASCADE"),
        nullable=True
    )

    cross_seeds = db.relationship(
        "Torrents",
        remote_side=[id],
        backref="parent_seed",
        passive_deletes=True
    )

    def __repr__(self):
        return f"<Torrent id={self.id} hash={self.hash}>"
