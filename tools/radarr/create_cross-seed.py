#!/usr/bin/env python3
import sys
import os
from pathlib import Path

# --- s'assurer que la racine du projet est dans sys.path ---
THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = THIS_FILE.parents[2]  # tools/radarr/ -> remontons de 2 niveaux
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Maintenant on peut importer les modules de l'application.
# On essaie plusieurs stratégies pour récupérer l'objet Flask `app`.
flask_app = None
try:
    # cas le plus courant : run.py définit `app = Flask(...)`
    import run as run_mod  # type: ignore
    flask_app = getattr(run_mod, "app", None)
except Exception:
    flask_app = None

if flask_app is None:
    try:
        # autre pattern : package app avec factory create_app
        # from app import create_app OR from app import app
        from app import create_app  # type: ignore
        flask_app = create_app()
    except Exception:
        try:
            from app import app as app_from_pkg  # type: ignore
            flask_app = app_from_pkg
        except Exception:
            flask_app = None

if flask_app is None:
    # dernier recours : essayer d'importer run and call create_app if exists
    try:
        import run as run_mod  # type: ignore
        if hasattr(run_mod, "create_app"):
            flask_app = run_mod.create_app()
    except Exception:
        flask_app = None

if flask_app is None:
    raise RuntimeError(
        "Impossible de trouver l'objet Flask `app`. "
        "Assure-toi que `run.py` expose `app` ou qu'un factory `create_app` existe dans `app`."
    )

# --- maintenant on peut importer le reste (après avoir réglé sys.path) ---
from app.extensions import db
from app.logger import get_logger
from app.models.torrents import Torrents
from app.models.movies import Movie

logger = get_logger(__name__)

# === CONFIG: change these test values as tu veux ===
RADARR_ID = "789"
MOVIE_TITLE = "Ratatouille 2: The Cheese Strikes Back"
# 4 sample hashes (parent + 3 cross seeds) — remplace si besoin
HASH_PARENT = "131fb13ea6946cf4a38ed6cda5fad89ersf4c4c1"
HASH_CHILD_1 = "131fb13ea6946cf4a12ud6cda5fad89ersf4c4c1"
HASH_CHILD_2 = "131fb15oa6946cf4b12ud6cda5fad89ersf4c4c1"
HASH_CHILD_3 = "131fb13ea6946cf4a12ud6cda5faz87ersf4c4c1"

def ensure_torrent(hashval: str, name: str) -> Torrents:
    """Return existing torrent or create it (committed)."""
    hash_norm = (hashval or "").strip().lower()
    existing = Torrents.query.filter_by(hash=hash_norm).first()
    if existing:
        logger.info("seed: torrent exists id=%s hash=%s name=%s", existing.id, existing.hash, existing.name)
        return existing

    t = Torrents(hash=hash_norm, name=name)
    db.session.add(t)
    try:
        db.session.commit()
        logger.info("seed: created torrent id=%s hash=%s name=%s", t.id, t.hash, t.name)
        return t
    except Exception:
        logger.exception("seed: failed to create torrent %s ; rollback and try to fetch existing", hash_norm)
        db.session.rollback()
        return Torrents.query.filter_by(hash=hash_norm).first()

def ensure_movie(radarr_id: str, title: str) -> Movie:
    """Return existing movie or create it (committed)."""
    existing = Movie.query.filter_by(radarr_id=str(radarr_id)).first()
    if existing:
        logger.info("seed: movie exists id=%s radarr_id=%s title=%s", existing.id, existing.radarr_id, existing.title)
        return existing

    m = Movie(radarr_id=str(radarr_id), title=title)
    db.session.add(m)
    try:
        db.session.commit()
        logger.info("seed: created movie id=%s radarr_id=%s title=%s", m.id, m.radarr_id, m.title)
        return m
    except Exception:
        logger.exception("seed: failed to create movie; rollback and fetch existing")
        db.session.rollback()
        return Movie.query.filter_by(radarr_id=str(radarr_id)).first()

def link_parent_and_children(parent: Torrents, children: list):
    """Set each child's cross_seed_id to parent.id (and commit)."""
    changed = False
    for c in children:
        if getattr(c, "cross_seed_id", None) != parent.id:
            c.cross_seed_id = parent.id
            db.session.add(c)
            changed = True
            logger.info("seed: linking child torrent id=%s hash=%s -> parent id=%s", c.id, c.hash, parent.id)
    if changed:
        try:
            db.session.commit()
            logger.info("seed: committed linking of %d children to parent %s", len(children), parent.id)
        except Exception:
            logger.exception("seed: commit failed while linking children; rollback")
            db.session.rollback()
    else:
        logger.info("seed: no child linking changes required")

def link_movie_to_parent(movie: Movie, parent: Torrents):
    """Set movie.latest_torrent_id to parent.id if needed and commit."""
    if getattr(movie, "latest_torrent_id", None) != parent.id:
        movie.latest_torrent_id = parent.id
        db.session.add(movie)
        try:
            db.session.commit()
            logger.info("seed: linked movie id=%s to parent torrent id=%s", movie.id, parent.id)
        except Exception:
            logger.exception("seed: failed to link movie -> rollback")
            db.session.rollback()
    else:
        logger.info("seed: movie already linked to torrent id=%s", parent.id)

def main():
    logger.info("seed: starting seed script")

    movie = ensure_movie(RADARR_ID, MOVIE_TITLE)

    parent = ensure_torrent(HASH_PARENT, f"{MOVIE_TITLE} (parent)")
    child1 = ensure_torrent(HASH_CHILD_1, f"{MOVIE_TITLE} (crossseed 1)")
    child2 = ensure_torrent(HASH_CHILD_2, f"{MOVIE_TITLE} (crossseed 2)")
    child3 = ensure_torrent(HASH_CHILD_3, f"{MOVIE_TITLE} (crossseed 3)")

    # link children -> parent
    link_parent_and_children(parent, [child1, child2, child3])

    # ensure movie -> parent
    link_movie_to_parent(movie, parent)

    # summary
    logger.info("seed: finished. movie.id=%s parent.id=%s children=%s", movie.id, parent.id, [c.id for c in (child1, child2, child3)])

if __name__ == "__main__":
    # Exécuter dans le contexte de l'app Flask trouvé plus haut
    with flask_app.app_context():
        try:
            main()
        except Exception as e:
            logger.exception("seed: unexpected error: %s", e)
            raise
