# app/repositories/torrents_repo.py
from typing import Optional, List, Set, Iterable
from sqlalchemy.exc import SQLAlchemyError
from app.logger import get_logger
from ..extensions import db
from ..models.torrents import Torrents

logger = get_logger(__name__)


def _normalize_hash(h: Optional[str]) -> Optional[str]:
    if not h:
        return None
    return h.strip().lower()


class TorrentsRepo:
    def __init__(self):
        self.logger = logger

    def get_by_id(self, id_: int) -> Optional[Torrents]:
        try:
            return db.session.query(Torrents).get(id_)
        except Exception:
            self.logger.exception("[BBDD] get_by_id failed for %s", id_)
            return None

    def get_by_hash(self, hashval: str) -> Optional[Torrents]:
        if not hashval:
            return None
        hv = _normalize_hash(hashval)
        try:
            return db.session.query(Torrents).filter(Torrents.hash == hv).first()
        except Exception:
            self.logger.exception("[BBDD] get_by_hash failed for %s", hv)
            return None

    def create(self, hashval: str, name: Optional[str] = None) -> Optional[Torrents]:
        if not hashval:
            raise ValueError("hashval is required")
        hv = _normalize_hash(hashval)
        # return existing if present
        existing = self.get_by_hash(hv)
        if existing:
            return existing

        t = Torrents(hash=hv, name=name)
        try:
            db.session.add(t)
            db.session.flush()
            db.session.commit()
            self.logger.info("[BBDD] Created Torrent id=%s hash=%s name=%s", t.id, t.hash, t.name)
            return t
        except Exception:
            self.logger.exception("[BBDD] create torrent failed for %s", hv)
            try:
                db.session.rollback()
            except Exception:
                self.logger.exception("[BBDD] rollback failed after create error")
            return self.get_by_hash(hv)

    def delete_by_hash(self, hashval: str) -> int:
        if not hashval:
            return 0
        hv = _normalize_hash(hashval)
        try:
            res = db.session.query(Torrents).filter(Torrents.hash == hv).delete(synchronize_session=False)
            # caller decides to commit/rollback; keep behavior similar to original
            db.session.commit()
            return res
        except Exception:
            self.logger.exception("[BBDD] delete_by_hash failed for %s", hv)
            try:
                db.session.rollback()
            except Exception:
                self.logger.exception("[BBDD] rollback failed after delete error")
            return 0

    def find_hashes_to_delete(self, parent_torrent_id: int) -> List[str]:
        parent_torrent = self.get_by_id(parent_torrent_id)
        hashes_to_delete = []
        hashes_to_delete.append(parent_torrent.hash.strip().lower())
        try:
            child_torrents = Torrents.query.filter_by(
                cross_seed_id=parent_torrent_id
            ).all()
        except Exception:
            self.logger.exception(
                "[BBDD] Erreur lors de la recherche des cross-seeds pour torrent_id=%s",
                parent_torrent_id
            )
            return hashes_to_delete
       
        for child in child_torrents:
            if child.hash:
                hashes_to_delete.append(child.hash.strip().lower())

        logger.info("[BBDD] Found %s cross-seed(s) for torrent_id=%s",len(hashes_to_delete), parent_torrent_id)
        return hashes_to_delete
