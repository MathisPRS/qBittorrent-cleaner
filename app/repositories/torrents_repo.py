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

        torrent = Torrents(hash=hv, name=name)
        try:
            db.session.add(torrent)
            db.session.flush()
            db.session.commit()
            self.logger.info("[BBDD] Created Torrent id=%s hash=%s name=%s", torrent.id, torrent.hash, torrent.name)
            return torrent
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
    
    def get_parent_by_name(self, name: str) -> Optional[Torrents]:
        if not name:
            return None
        try:
            
            return db.session.query(Torrents).filter(
                Torrents.name == name,
                Torrents.cross_seed_id == None
            ).first()
        except Exception:
            self.logger.exception("[BBDD] get_parent_by_name failed for %s", name)
            return None
        
    def set_cross_seed_parent(self, child_hash: str, parent_id: int) -> Optional[Torrents]:
        if not child_hash or not parent_id:
            return None

        hash = _normalize_hash(child_hash)
        try:
            cross_seed_torrent = db.session.query(Torrents).filter(Torrents.hash == hash).first()
            if not cross_seed_torrent:
                self.logger.warning("[BBDD] set_cross_seed_parent: child not found for hash=%s", hash)
                return None

            # si déjà lié au même parent, on renvoie tel quel
            if cross_seed_torrent.cross_seed_id == parent_id:
                self.logger.info("[BBDD] set_cross_seed_parent: already linked child_id=%s parent_id=%s", cross_seed_torrent.id, parent_id)
                return cross_seed_torrent

            cross_seed_torrent.cross_seed_id = parent_id
            db.session.add(cross_seed_torrent)
            db.session.commit()
            self.logger.info("[BBDD] Linked torrent id=%s (hash=%s) to parent_id=%s", cross_seed_torrent.id, cross_seed_torrent.hash, parent_id)
            return cross_seed_torrent
        except Exception:
            self.logger.exception("[BBDD] set_cross_seed_parent failed for %s -> %s", hash, parent_id)
            try:
                db.session.rollback()
            except Exception:
                self.logger.exception("[BBDD] rollback failed after set_cross_seed_parent error")
            return None
