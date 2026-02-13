# app/repositories/torrents_repo.py
from ..extensions import db
from ..models.torrents import Torrents

class TorrentsRepo:
    def get_by_id(self, id_):
        return Torrents.query.get(id_)

    def get_by_hash(self, hashval):
        if not hashval:
            return None
        return Torrents.query.filter_by(hash=hashval).first()

    def create(self, hashval, name=None):
        t = Torrents(hash=hashval, name=name)
        db.session.add(t)
        try:
            db.session.commit()
            return t
        except Exception:
            db.session.rollback()
            return self.get_by_hash(hashval)

    def delete_by_hash(self, hashval):
        if not hashval:
            return 0
        rows = Torrents.query.filter_by(hash=hashval).delete()
        db.session.commit()
        return rows

    def find_cross_seed_hashes(self, torrent_id):
        # Garantie le hash du torrent_id
        if not torrent_id:
            return []

        root = self.get_by_id(torrent_id)
        if not root:
            return []

        hashes = set()
        stack = [root]
        while stack:
            node = stack.pop()
            # ajoute le hash du node si présent
            if getattr(node, "hash", None):
                hashes.add(node.hash)
            # ajoute les enfants à la pile
            children = getattr(node, "cross_seeds", []) or []
            for c in children:
                stack.append(c)

        # force-to-list: si root existe mais sans hash (incohérence), on retourne [] — caller pourra gérer
        return list(hashes)

