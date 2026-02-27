# repositories/deferred_deletions_repo.py
from datetime import datetime
from typing import Optional, List
from sqlalchemy.exc import SQLAlchemyError

from ..extensions import db
from ..models.deferred_deletion import DeferredDeletion
from app.logger import get_logger

logger = get_logger(__name__)


class DeferredDeletionsRepo:

    def create_if_not_exists(self, torrent_hash: str, name: Optional[str], can_be_deleted_at: datetime) -> bool:
        if not torrent_hash:
            logger.debug("create_if_not_exists: empty torrent_hash -> skip")
            return False

        try:
            existing = db.session.query(DeferredDeletion).filter_by(torrent_hash=torrent_hash).one_or_none()
            if existing:
                logger.debug("create_if_not_exists: already exists for hash=%s", torrent_hash)
                return False

            row = DeferredDeletion(
                name=name,
                torrent_hash=torrent_hash,
                can_be_deleted_at=can_be_deleted_at
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
        

    def delete_many(self, hashes: List[str]) -> int:
        if not hashes:
            logger.debug("delete_many: empty hashes -> nothing to delete")
            return 0

        try:
            query = db.session.query(DeferredDeletion).filter(DeferredDeletion.torrent_hash.in_(hashes))
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