# repositories/deferred_deletions_repo.py
from datetime import datetime
from typing import Optional, List
from ..extensions import db
from ..models.deferred_deletion import DeferredDeletion
from sqlalchemy.exc import SQLAlchemyError

class DeferredDeletionsRepo:

    def create_if_not_exists(self, torrent_hash: str, name: Optional[str], can_be_deleted_at: datetime) -> bool:
        if not torrent_hash:
            return False
        try:
            existing = db.session.query(DeferredDeletion).filter_by(torrent_hash=torrent_hash).one_or_none()
            if existing:
                return False
            dd = DeferredDeletion(name=name, torrent_hash=torrent_hash, can_be_deleted_at=can_be_deleted_at)
            db.session.add(dd)
            db.session.commit()
            return True
        except SQLAlchemyError:
            db.session.rollback()
            raise

    def delete_many(self, hashes: List[str]) -> int:
        if not hashes:
            return 0
        try:
            q = db.session.query(DeferredDeletion).filter(DeferredDeletion.torrent_hash.in_(hashes))
            n = q.delete(synchronize_session=False)
            db.session.commit()
            return n
        except SQLAlchemyError:
            db.session.rollback()
            raise