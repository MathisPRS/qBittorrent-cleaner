# app/models/__init__.py
from ..extensions import db
from .movies import Movie
from .series import Series
from .torrents import Torrents

__all__ = ["db", "Movie", "Series","Episodes", "Torrents"]
