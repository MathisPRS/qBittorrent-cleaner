#!/usr/bin/env python3
import sys
import os
from pathlib import Path

# --- s'assurer que la racine du projet est dans sys.path ---
THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = THIS_FILE.parents[2]  # adapte si tu mets le script ailleurs
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Maintenant on peut importer l'app / factory
flask_app = None
try:
    import run as run_mod  # type: ignore
    flask_app = getattr(run_mod, "app", None)
except Exception:
    flask_app = None

if flask_app is None:
    try:
        from app import create_app  # type: ignore
        flask_app = create_app()
    except Exception:
        try:
            from app import app as app_from_pkg  # type: ignore
            flask_app = app_from_pkg
        except Exception:
            flask_app = None

if flask_app is None:
    # dernier essai
    try:
        import run as run_mod  # type: ignore
        if hasattr(run_mod, "create_app"):
            flask_app = run_mod.create_app()
    except Exception:
        flask_app = None

if flask_app is None:
    raise RuntimeError(
        "Impossible de trouver l'objet Flask `app`. "
        "Assure-toi que `run.py` expose `app` ou qu'une factory `create_app` existe dans `app`."
    )

# --- imports après acquisition du flask app ---
from app.extensions import db
from app.logger import get_logger
from app.models.torrents import Torrents
from app.models.series import Series
from app.models.episodes import Episodes

logger = get_logger(__name__)

# === CONFIG DE TEST ===
SONARR_ID = "666"
SERIES_TITLE = "TEST"

# Générer 12 hashes de test (tu peux remplacer par tes propres valeurs)
def make_hash(i: int) -> str:
    # hash factice, suffisamment long et unique
    return f"testhash_{i:02d}_131fb13ea6946cf4a38ed6cda5fad89e{i:02d}"

# helpers
def ensure_torrent(hashval: str, name: str = None) -> Torrents:
    """Return existing torrent or create it (committed)."""
    hv = (hashval or "").strip().lower()
    existing = Torrents.query.filter_by(hash=hv).first()
    if existing:
        logger.info("seed: torrent exists id=%s hash=%s name=%s", existing.id, existing.hash, existing.name)
        return existing

    t = Torrents(hash=hv, name=name)
    db.session.add(t)
    try:
        db.session.commit()
        logger.info("seed: created torrent id=%s hash=%s name=%s", t.id, t.hash, t.name)
        return t
    except Exception:
        logger.exception("seed: failed to create torrent %s ; rollback and try to fetch existing", hv)
        db.session.rollback()
        return Torrents.query.filter_by(hash=hv).first()

def ensure_series(sonarr_id: str, title: str) -> Series:
    """Return existing series or create it (committed)."""
    existing = Series.query.filter_by(sonarr_id=str(sonarr_id)).first()
    if existing:
        logger.info("seed: series exists id=%s sonarr_id=%s title=%s", existing.id, existing.sonarr_id, existing.title)
        return existing

    s = Series(sonarr_id=str(sonarr_id), title=title)
    db.session.add(s)
    try:
        db.session.commit()
        logger.info("seed: created series id=%s sonarr_id=%s title=%s", s.id, s.sonarr_id, s.title)
        return s
    except Exception:
        logger.exception("seed: failed to create series; rollback and fetch existing")
        db.session.rollback()
        return Series.query.filter_by(sonarr_id=str(sonarr_id)).first()

def create_episode(series_obj: Series, season: int, episode_num: int, latest_torrent: Torrents, title: str = None) -> Episodes:
    """Create an episode row linked to series_obj and torrent; returns Episodes instance."""
    # Respecte ton modèle Episodes: fields (serie_id, title, season, episode, latest_torrent_id)
    e = Episodes(
        serie_id=series_obj.id,
        title=title or f"{series_obj.title} S{season:02d}E{episode_num:02d}",
        season=season,
        episode=episode_num,
        latest_torrent_id=latest_torrent.id
    )
    db.session.add(e)
    try:
        db.session.commit()
        logger.info("seed: created episode id=%s %s S%02dE%02d linked to torrent id=%s", e.id, series_obj.title, season, episode_num, latest_torrent.id)
        return e
    except Exception:
        logger.exception("seed: failed to create episode S%02dE%02d ; rollback", season, episode_num)
        db.session.rollback()
        return Episodes.query.filter_by(serie_id=series_obj.id, season=season, episode=episode_num).first()

def link_children_to_parent(parent: Torrents, children: list):
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

def main():
    logger.info("seed: starting sonarr series seed script")

    # ensure series exists
    series = ensure_series(SONARR_ID, SERIES_TITLE)

    # create 12 distinct torrents and episodes S01E01..S01E12
    torrents = []
    episodes = []
    for i in range(1, 13):
        h = make_hash(i)
        t = ensure_torrent(h, f"{SERIES_TITLE} - torrent {i}")
        torrents.append(t)

    # create episodes linked to each torrent
    for i, t in enumerate(torrents, start=1):
        ep = create_episode(series, season=1, episode_num=i, latest_torrent=t, title=f"{SERIES_TITLE} S01E{i:02d}")
        episodes.append(ep)

    # For episode S01E02 (index 1), create 2 cross-seeds that point to its parent torrent
    parent_for_e2 = torrents[1]  # index 1 -> episode 2
    cross1 = ensure_torrent(make_hash(100), f"{SERIES_TITLE} S01E02 crossseed 1")
    cross2 = ensure_torrent(make_hash(101), f"{SERIES_TITLE} S01E02 crossseed 2")

    # Link cross1 and cross2 as children of parent_for_e2
    link_children_to_parent(parent_for_e2, [cross1, cross2])

    # Summary log
    logger.info(
        "seed: finished. series.id=%s sonarr_id=%s episodes_created=%s parent_e2_id=%s cross_children=%s",
        series.id,
        series.sonarr_id,
        [getattr(e, "id", None) for e in episodes],
        parent_for_e2.id,
        [c.id for c in (cross1, cross2)]
    )

if __name__ == "__main__":
    with flask_app.app_context():
        try:
            main()
        except Exception as e:
            logger.exception("seed: unexpected error: %s", e)
            raise
