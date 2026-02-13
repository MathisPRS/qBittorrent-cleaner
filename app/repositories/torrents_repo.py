# app/repositories/torrent_repo.py
from ..extensions import db
from ..models.torrents import Torrents
from sqlalchemy.exc import IntegrityError

class TorrentsRepo:
    def create(self, hash, commit=True):
        """
        Create a Torrent row. If hash is None, create a placeholder row.
        Raises IntegrityError if unique constraint violated.
        """
        t = Torrents(hash=hash)
        
        db.session.add(t)
        if commit:
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                # another concurrent creator may have created it -> fetch existing
                return self.get_by_hash(hash)
        return t

    def get_by_hash(self, hash):
        if not hash:
            return None
        return Torrents.query.filter_by(hash=hash).first()
    

    def delete_by_hash(self, hash):
        Torrents.query.filter_by(hash=hash).delete()
        db.session.commit()
