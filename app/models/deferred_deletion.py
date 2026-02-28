from sqlalchemy import Column, Integer, String, DateTime, func, UniqueConstraint
from ..extensions import db

class DeferredDeletion(db.Model):
    __tablename__ = "deferred_deletions"

    id = Column(Integer, primary_key=True)
    name = Column(String(512), nullable=True)              # nom human-friendly (facultatif)
    torrent_hash = Column(String(128), nullable=False, index=True)
    can_be_deleted_at = Column(DateTime(timezone=True), nullable=False)
    requested_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    celery_task_id = db.Column(db.String(255), nullable=True)

    __table_args__ = (
        UniqueConstraint("torrent_hash", name="uq_deferred_torrent_hash"),
    )