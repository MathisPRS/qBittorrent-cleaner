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

    def find_hashes_to_delete(self, torrent_id: int) -> List[str]:
        if not torrent_id:
            return []

        root = self.get_by_id(torrent_id)
        if not root:
            return []

        hashes: Set[str] = set()
        stack = [root]

        while stack:
            node = stack.pop()
            if not node:
                continue

            # add node hash if present
            h = _normalize_hash(getattr(node, "hash", None))
            if h:
                hashes.add(h)

            # children may be a list (normal), or (unexpectedly) a single Torrents instance
            children = getattr(node, "cross_seeds", None)
            if not children:
                continue

            # If it's an iterable of children (list/tuple etc.) iterate, otherwise push single child
            # Exclude strings by checking isinstance(children, (str, bytes))
            if isinstance(children, Iterable) and not isinstance(children, (str, bytes)):
                # Some ORMs return instrumented lists that are Iterable
                for c in children:
                    if c:
                        stack.append(c)
            else:
                # Single child case: push it
                stack.append(children)

        return list(hashes)
