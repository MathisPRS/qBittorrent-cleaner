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
    
    def get_parent_by_name(self, name: str, exclude_id: Optional[int] = None) -> Optional[Torrents]:
        if not name:
            return None
        try:
            q = db.session.query(Torrents).filter(
                Torrents.name == name,
                Torrents.cross_seed_id.is_(None)
            )
            if exclude_id is not None:
                q = q.filter(Torrents.id != exclude_id)
            return q.first()
        except Exception:
            self.logger.exception("[BBDD] get_parent_by_name failed for %s (exclude=%s)", name, exclude_id)
            return None
        
    def set_cross_seed_parent(self, child_hash: str, parent_id: int, child_name: Optional[str] = None) -> Optional[Torrents]:
        """
        Lie un torrent enfant (identifié par son hash) à un parent (parent_id)
        en mettant à jour child.cross_seed_id = parent_id et, si fourni, child.name = child_name.
        Retourne l'objet Torrent mis à jour ou None si échec.
        """

        if not child_hash or parent_id is None:
            self.logger.warning("[BBDD] set_cross_seed_parent called with missing args: hash=%s parent_id=%s", child_hash, parent_id)
            return None

        hv = _normalize_hash(child_hash)
        try:
            torrent = db.session.query(Torrents).filter(Torrents.hash == hv).first()
            if not torrent:
                self.logger.warning("[BBDD] set_cross_seed_parent: child not found for hash=%s", hv)
                return None

            changed = False

            # Mettre à jour le nom si fourni et différent
            if child_name is not None and (torrent.name != child_name):
                torrent.name = child_name
                changed = True
                self.logger.debug("[BBDD] Updating torrent name for id=%s hash=%s -> %s", torrent.id, hv, child_name)

            # Toujours essayer de mettre à jour le cross_seed_id (force update)
            if torrent.cross_seed_id != parent_id:
                torrent.cross_seed_id = parent_id
                changed = True
                self.logger.debug("[BBDD] Setting cross_seed_id for torrent id=%s to parent_id=%s", torrent.id, parent_id)
            else:
                # Même valeur : on logge mais on considère quand même l'opération comme OK
                self.logger.info("[BBDD] set_cross_seed_parent: cross_seed_id already %s for torrent id=%s", parent_id, torrent.id)

            if changed:
                db.session.add(torrent)
                db.session.commit()
                self.logger.info("[BBDD] Linked/updated torrent id=%s (hash=%s) to parent_id=%s", torrent.id, hv, parent_id)
            else:
                # Même si rien à commit, renvoyer l'objet pour confort caller
                self.logger.debug("[BBDD] No DB change required for torrent id=%s (hash=%s)", torrent.id, hv)

            return torrent
        except Exception:
            self.logger.exception("[BBDD] set_cross_seed_parent failed for %s -> %s", hv, parent_id)
            try:
                db.session.rollback()
            except Exception:
                self.logger.exception("[BBDD] rollback failed after set_cross_seed_parent error")
            return None