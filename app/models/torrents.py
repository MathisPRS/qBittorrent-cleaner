from datetime import datetime
from ..extensions import db

class Torrents(db.Model):
    __tablename__ = "torrents"

    id = db.Column(db.Integer, primary_key=True)
    hash = db.Column(db.String(128), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
