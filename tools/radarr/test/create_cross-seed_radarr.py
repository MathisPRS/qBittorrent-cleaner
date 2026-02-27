#!/usr/bin/env python3
import sys
import os
from pathlib import Path
from typing import Optional

# ----------------------------------------
# Résolution automatique de la racine projet
# ----------------------------------------
THIS_FILE = Path(__file__).resolve()

def find_project_root(start: Path, max_levels: int = 6) -> Optional[Path]:
    """
    Remonte l'arbre depuis `start` jusqu'à `max_levels` parents pour trouver
    un répertoire contenant soit un dossier 'app', soit un fichier 'run.py'.
    Retourne le Path du project root ou None si non trouvé.
    """
    p = start
    for _ in range(max_levels + 1):
        if (p / "app").is_dir() or (p / "run.py").is_file():
            return p
        if p.parent == p:
            break
        p = p.parent
    return None

PROJECT_ROOT = find_project_root(THIS_FILE.parent)
if PROJECT_ROOT is None:
    # fallback : utiliser deux niveaux au-dessus comme tu faisais, mais avertir
    PROJECT_ROOT = THIS_FILE.parents[2] if len(THIS_FILE.parents) >= 3 else THIS_FILE.parent
    # on n'échoue pas immédiatement pour garder tolérance, mais on logera si import fail

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ----------------------------------------
# Tentatives pour récupérer un objet Flask `app`
# ----------------------------------------
flask_app = None
import importlib
import traceback

_import_errors = []

def try_import_run_module():
    try:
        run_mod = importlib.import_module("run")
        return run_mod
    except Exception as exc:
        _import_errors.append(("import run", exc, traceback.format_exc()))
        return None

def try_from_app_import_create_app():
    try:
        # tente d'importer la factory create_app depuis le package app
        mod = importlib.import_module("app")
        create_app = getattr(mod, "create_app", None)
        if callable(create_app):
            return create_app
        # fallback: maybe app.__init__ doesn't expose create_app but package has create_app attribute
        # try import from app.__init__ explicitly (same as above though)
        return None
    except Exception as exc:
        _import_errors.append(("from app import create_app", exc, traceback.format_exc()))
        return None

def try_from_app_import_app_instance():
    try:
        mod = importlib.import_module("app")
        app_inst = getattr(mod, "app", None)
        if app_inst is not None:
            return app_inst
        return None
    except Exception as exc:
        _import_errors.append(("from app import app", exc, traceback.format_exc()))
        return None

# 1) try run module
run_mod = try_import_run_module()
if run_mod is not None:
    # prefer run.app if présent
    flask_app = getattr(run_mod, "app", None)
    if callable(getattr(run_mod, "create_app", None)) and flask_app is None:
        try:
            flask_app = run_mod.create_app()
        except Exception as exc:
            _import_errors.append(("run.create_app()", exc, traceback.format_exc()))

# 2) try app.create_app
if flask_app is None:
    create_app_candidate = try_from_app_import_create_app()
    if callable(create_app_candidate):
        try:
            flask_app = create_app_candidate()
        except Exception as exc:
            _import_errors.append(("app.create_app()", exc, traceback.format_exc()))

# 3) try app.app instance
if flask_app is None:
    flask_app = try_from_app_import_app_instance()

# 4) last-resort: re-check run module for create_app if not checked above
if flask_app is None and run_mod is not None and callable(getattr(run_mod, "create_app", None)):
    try:
        flask_app = run_mod.create_app()
    except Exception as exc:
        _import_errors.append(("run.create_app() second try", exc, traceback.format_exc()))

if flask_app is None:
    # diagnostic utile pour debug : afficher tentatives et racine testée
    diag = {
        "project_root": str(PROJECT_ROOT),
        "sys_path_head": sys.path[0],
        "import_attempts": [
            {"step": step, "error": str(err), "traceback_snippet": tb.splitlines()[:5]}
            for (step, err, tb) in _import_errors
        ]
    }
    raise RuntimeError(
        "Impossible de trouver ou d'initialiser l'objet Flask `app`.\n"
        f"Diagnostique: {diag}\n"
        "Assure-toi que `run.py` expose `app` ou qu'une factory `create_app` existe dans le package `app`."
    )

# ----------------------------------------
# Maintenant imports d'app (après avoir obtenu flask_app et sys.path)
# ----------------------------------------
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
