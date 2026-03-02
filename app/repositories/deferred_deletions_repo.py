from datetime import datetime
from typing import Optional, List
from sqlalchemy.exc import SQLAlchemyError

from ..extensions import db
from ..models.deferred_deletions import DeferredDeletions
from app.logger import get_logger

logger = get_logger(__name__)

class DeferredDeletionsRepo:

    def create_if_not_exists(self, torrent_hash: str, name: Optional[str], can_be_deleted_at: datetime, celery_task_id: Optional[str] = None) -> bool:
        if not torrent_hash:
            logger.debug("create_if_not_exists: empty torrent_hash -> skip")
            return False

        try:
            existing = db.session.query(DeferredDeletions).filter_by(torrent_hash=torrent_hash).one_or_none()
            if existing:
                logger.debug("create_if_not_exists: already exists for hash=%s", torrent_hash)
                return False

            row = DeferredDeletions(
                name=name,
                torrent_hash=torrent_hash,
                can_be_deleted_at=can_be_deleted_at,
                celery_task_id=celery_task_id
            )
            db.session.add(row)
            db.session.commit()

            logger.info("Created DeferredDeletion id=%s hash=%s", getattr(row, "id", None), torrent_hash)
            return True

        except SQLAlchemyError:
            logger.exception("create_if_not_exists: DB error for hash=%s", torrent_hash)
            try:
                db.session.rollback()
            except Exception:
                logger.exception("create_if_not_exists: rollback failed for hash=%s", torrent_hash)
            return False
        

    def get_by_hash(self, torrent_hash: str) -> Optional[DeferredDeletions]:
        if not torrent_hash:
            return None
        try:
            return db.session.query(DeferredDeletions).filter(DeferredDeletions.torrent_hash == torrent_hash).first()
        except Exception:
            logger.exception("get_by_hash failed for %s", torrent_hash)
            return None
        

    def set_task_id_for_hash(self, torrent_hash: str, task_id: str) -> bool:
        if not torrent_hash:
            return False
        try:
            row = db.session.query(DeferredDeletions).filter(DeferredDeletions.torrent_hash == torrent_hash).one_or_none()
            if not row:
                return False
            row.celery_task_id = task_id
            db.session.add(row)
            db.session.commit()
            logger.info("set_task_id_for_hash: stored task_id for %s", torrent_hash)
            return True
        except Exception:
            logger.exception("set_task_id_for_hash failed for %s", torrent_hash)
            try:
                db.session.rollback()
            except Exception:
                logger.exception("set_task_id_for_hash: rollback failed")
            return False
        

    def list_batch(self, limit: int = 500, offset: int = 0) -> List[DeferredDeletions]:
        try:
            q = db.session.query(DeferredDeletions).order_by(DeferredDeletions.id).limit(limit).offset(offset)
            return q.all()
        except Exception:
            logger.exception("list_batch failed (limit=%s offset=%s)", limit, offset)
            return []
        
        
    def delete_many(self, hashes: List[str]) -> int:
        if not hashes:
            logger.debug("delete_many: empty hashes -> nothing to delete")
            return 0

        try:
            query = db.session.query(DeferredDeletions).filter(DeferredDeletions.torrent_hash.in_(hashes))
            rows_deleted = query.delete(synchronize_session=False)
            db.session.commit()

            logger.info("Deleted %d deferred row(s) for %d hash(es)", rows_deleted, len(hashes))
            return int(rows_deleted)

        except SQLAlchemyError:
            logger.exception("delete_many: DB error while deleting hashes=%s", hashes)
            try:
                db.session.rollback()
            except Exception:
                logger.exception("delete_many: rollback failed while deleting hashes=%s", hashes)
            return 0