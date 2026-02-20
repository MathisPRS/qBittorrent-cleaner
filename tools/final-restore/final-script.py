#!/usr/bin/env python3
"""
Import optimisé pour JSON combiné movies + series.

Usage:
  python tools/imports/import_movies_series_optimized.py /chemin/vers/data_all.json

Hypothèses:
- Base VIDE (on crée tout sans vérifier l'existence).
- movies: list of { id_radarr, title, torrents: [...] }
- series: list of { series_id, seriesTitle, episodes: [ { episode_id, season, episode, title, torrents:[...] } ] }
- For each entity, the FIRST torrent in the list is considered the "latest" (linked to movie.latest_torrent_id or episode.latest_torrent_id).
- Each torrent item: { hash, qb_name, qb_indexer, qb_added_on_paris, cross_seed: [...] }
"""
import sys
import json
from pathlib import Path
from itertools import islice
from typing import Iterable, List, Tuple, Dict, Optional

THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = THIS_FILE.parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# --- recover flask app ---
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
    try:
        import run as run_mod  # type: ignore
        if hasattr(run_mod, "create_app"):
            flask_app = run_mod.create_app()
    except Exception:
        flask_app = None

if flask_app is None:
    raise RuntimeError("Impossible de trouver l'objet Flask `app`. Expose `app` ou `create_app`.")

# --- imports DB + models after obtaining app context ---
from app.extensions import db
from app.logger import get_logger
from app.models.torrents import Torrents
from app.models.movies import Movie
from app.models.series import Series
from app.models.episodes import Episodes

logger = get_logger(__name__)

# --- batch sizes (tuneable) ---
TORRENT_BATCH = 2000
MOVIE_BATCH = 1000
SERIES_BATCH = 500
EPISODE_BATCH = 2000
LINK_BATCH = 2000

# -------------------------
# Utilities
# -------------------------
def chunks_iterable(iterable: Iterable, size: int):
    it = iter(iterable)
    while True:
        chunk = list(islice(it, size))
        if not chunk:
            break
        yield chunk

def safe_setattr(obj, name: str, value):
    """Set attribute only if model has attribute (defensive)."""
    if value is None:
        return
    if hasattr(obj, name):
        setattr(obj, name, value)

# -------------------------
# JSON parsing helpers
# -------------------------
def collect_torrents_from_json(data: dict) -> List[Tuple[str, Optional[str], Optional[str], Optional[str]]]:
    """
    Return list of (hash, qb_name, qb_indexer, qb_added_on_paris) for every torrent and cross-seed in JSON.
    Deduplicated by hash (first occurrence wins).
    """
    seen = {}
    out = []

    # movies
    for m in data.get("movies", []) or []:
        for t in m.get("torrents", []) or []:
            h = (t.get("hash") or "").strip().lower()
            if not h:
                continue
            if h in seen:
                continue
            seen[h] = True
            out.append((h, t.get("qb_name") or None, t.get("qb_indexer") or None, t.get("qb_added_on_paris") or None))
            # cross seeds for this torrent
            for cs in (t.get("cross_seed") or []):
                ch = (cs.get("hash") or "").strip().lower()
                if not ch or ch in seen:
                    continue
                seen[ch] = True
                out.append((ch, cs.get("qb_name") or None, cs.get("qb_indexer") or None, None))

    # series/episodes
    for s in data.get("series", []) or []:
        for ep in (s.get("episodes") or []):
            for t in (ep.get("torrents") or []):
                h = (t.get("hash") or "").strip().lower()
                if not h:
                    continue
                if h in seen:
                    continue
                seen[h] = True
                out.append((h, t.get("qb_name") or None, t.get("qb_indexer") or None, t.get("qb_added_on_paris") or None))
                for cs in (t.get("cross_seed") or []):
                    ch = (cs.get("hash") or "").strip().lower()
                    if not ch or ch in seen:
                        continue
                    seen[ch] = True
                    out.append((ch, cs.get("qb_name") or None, cs.get("qb_indexer") or None, None))

    return out

# -------------------------
# Main import function
# -------------------------
def import_movies_and_series(json_path: str):
    p = Path(json_path)
    if not p.exists():
        raise SystemExit(f"file not found: {json_path}")

    data = json.loads(p.read_text(encoding="utf-8"))

    # collect unique torrents (hash,name,indexer,added_at)
    torrent_list = collect_torrents_from_json(data)
    logger.info("Import: discovered %d unique torrents to create", len(torrent_list))

    with flask_app.app_context():
        # 1) create Torrents in batches, build hash -> id map
        hash_to_id: Dict[str, int] = {}
        total_created = 0
        for batch in chunks_iterable(torrent_list, TORRENT_BATCH):
            objs = []
            for (h, name, indexer, added_on) in batch:
                t = Torrents(hash=h, name=name)
                # defensive fields
                safe_setattr(t, "indexer", indexer)
                # if model has 'added_at' or similar, try to set from qb_added_on_paris
                if hasattr(t, "added_at") and added_on:
                    # store raw string; if model expects datetime, convert here (naive) -- try best-effort
                    try:
                        # prefer storing ISO string if model is String; else try parse ISO to datetime
                        import dateutil.parser as dp  # type: ignore
                        dt = dp.parse(added_on)
                        safe_setattr(t, "added_at", dt)
                    except Exception:
                        safe_setattr(t, "added_at", added_on)
                objs.append(t)
            db.session.add_all(objs)
            try:
                db.session.commit()
            except Exception:
                logger.exception("Import: commit failed when inserting torrents; rollback and abort")
                db.session.rollback()
                raise
            for o in objs:
                if getattr(o, "hash", None):
                    hash_to_id[o.hash.strip().lower()] = o.id
            total_created += len(objs)
            logger.info("Import: committed %d torrents (total %d)", len(objs), total_created)

        # 2) create Movies (Radarr)
        movies_in = data.get("movies", []) or []
        movie_objs = []
        movie_radarr_id_to_dbid = {}
        for m in movies_in:
            rad_id = m.get("id_radarr")
            title = m.get("title")
            # choose latest torrent as first in list if exists
            first_t = (m.get("torrents") or [None])[0] or {}
            first_hash = (first_t.get("hash") or "").strip().lower() or None
            latest_tid = hash_to_id.get(first_hash) if first_hash else None
            movie_objs.append(Movie(radarr_id=str(rad_id) if rad_id is not None else None, title=title, latest_torrent_id=latest_tid))
        created_movies = 0
        for batch in chunks_iterable(movie_objs, MOVIE_BATCH):
            db.session.add_all(batch)
            try:
                db.session.commit()
            except Exception:
                logger.exception("Import: commit failed when inserting movies; rollback")
                db.session.rollback()
                raise
            for o in batch:
                movie_radarr_id_to_dbid[o.radarr_id] = o.id
            created_movies += len(batch)
            logger.info("Import: committed %d movies (total %d)", len(batch), created_movies)

        # 3) create Series
        series_in = data.get("series", []) or []
        series_objs = []
        series_id_map = {}
        for s in series_in:
            sid = s.get("series_id")
            title = s.get("seriesTitle") or None
            series_objs.append(Series(sonarr_id=str(sid) if sid is not None else None, title=title))
        created_series = 0
        for batch in chunks_iterable(series_objs, SERIES_BATCH):
            db.session.add_all(batch)
            try:
                db.session.commit()
            except Exception:
                logger.exception("Import: commit failed when inserting series; rollback")
                db.session.rollback()
                raise
            for o in batch:
                series_id_map[o.sonarr_id] = o.id
            created_series += len(batch)
            logger.info("Import: committed %d series (total %d)", len(batch), created_series)

        # 4) create Episodes: iterate series->episodes and create episode objects using first torrent as latest
        episode_objs = []
        for s in series_in:
            s_db_id = series_id_map.get(str(s.get("series_id")))
            if s_db_id is None:
                logger.warning("Import: skipping series that was not created: %s", s)
                continue
            for ep in (s.get("episodes") or []):
                season = ep.get("season")
                epnum = ep.get("episode")
                title = ep.get("title") or None
                first_t = (ep.get("torrents") or [None])[0] or {}
                first_hash = (first_t.get("hash") or "").strip().lower() or None
                latest_tid = hash_to_id.get(first_hash) if first_hash else None
                e = Episodes(serie_id=s_db_id, season=season, episode=epnum, title=title, latest_torrent_id=latest_tid)
                # set qb_added_at if model has attribute and available
                if hasattr(e, "added_at") and first_t.get("qb_added_on_paris"):
                    try:
                        import dateutil.parser as dp  # type: ignore
                        e.added_at = dp.parse(first_t.get("qb_added_on_paris"))
                    except Exception:
                        pass
                episode_objs.append(e)

        created_episodes = 0
        for batch in chunks_iterable(episode_objs, EPISODE_BATCH):
            db.session.add_all(batch)
            try:
                db.session.commit()
            except Exception:
                logger.exception("Import: commit failed when inserting episodes; rollback")
                db.session.rollback()
                raise
            created_episodes += len(batch)
            logger.info("Import: committed %d episodes (total %d)", len(batch), created_episodes)

        # 5) Link cross-seeds: use hash_to_id mapping to update child.cross_seed_id -> parent.id
        link_count = 0
        def link_child_parent(child_hash: str, parent_hash: str) -> bool:
            ch = (child_hash or "").strip().lower()
            ph = (parent_hash or "").strip().lower()
            if not ch or not ph:
                return False
            child_id = hash_to_id.get(ch)
            parent_id = hash_to_id.get(ph)
            if not child_id or not parent_id:
                logger.warning("Import: link skipped miss mapping child=%s parent=%s", ch, ph)
                return False
            try:
                db.session.query(Torrents).filter(Torrents.id == child_id).update({"cross_seed_id": parent_id})
                db.session.commit()
                return True
            except Exception:
                logger.exception("Import: failed linking child=%s -> parent=%s", ch, ph)
                db.session.rollback()
                return False

        # iterate movies
        for m in movies_in:
            first = (m.get("torrents") or [None])[0] or {}
            parent_h = (first.get("hash") or "").strip().lower() or None
            for t in (m.get("torrents") or []):
                for cs in (t.get("cross_seed") or []):
                    child_h = (cs.get("hash") or "").strip().lower()
                    if child_h and parent_h:
                        if link_child_parent(child_h, parent_h):
                            link_count += 1

        # iterate series/episodes
        for s in series_in:
            for ep in (s.get("episodes") or []):
                first = (ep.get("torrents") or [None])[0] or {}
                parent_h = (first.get("hash") or "").strip().lower() or None
                for t in (ep.get("torrents") or []):
                    for cs in (t.get("cross_seed") or []):
                        child_h = (cs.get("hash") or "").strip().lower()
                        if child_h and parent_h:
                            if link_child_parent(child_h, parent_h):
                                link_count += 1

        # 6) Update torrent indexer and qb_name where available (batch updates)
        updates = 0
        def update_torrent_fields(hashv: str, name: Optional[str], indexer: Optional[str]):
            if not hashv:
                return False
            hv = hashv.strip().lower()
            tid = hash_to_id.get(hv)
            if not tid:
                return False
            upd = {}
            if name and hasattr(Torrents, "name"):
                upd["name"] = name
            if indexer and hasattr(Torrents, "indexer"):
                upd["indexer"] = indexer
            if not upd:
                return False
            try:
                db.session.query(Torrents).filter(Torrents.id == tid).update(upd)
                db.session.commit()
                return True
            except Exception:
                logger.exception("Import: failed to update torrent fields for %s", hv)
                db.session.rollback()
                return False

        # movies -> update fields
        for m in movies_in:
            for t in (m.get("torrents") or []):
                if update_torrent_fields(t.get("hash"), t.get("qb_name"), t.get("qb_indexer")):
                    updates += 1
                for cs in (t.get("cross_seed") or []):
                    if update_torrent_fields(cs.get("hash"), cs.get("qb_name"), cs.get("qb_indexer")):
                        updates += 1

        # series -> update fields
        for s in series_in:
            for ep in (s.get("episodes") or []):
                for t in (ep.get("torrents") or []):
                    if update_torrent_fields(t.get("hash"), t.get("qb_name"), t.get("qb_indexer")):
                        updates += 1
                    for cs in (t.get("cross_seed") or []):
                        if update_torrent_fields(cs.get("hash"), cs.get("qb_name"), cs.get("qb_indexer")):
                            updates += 1

        # final summary
        summary = {
            "torrents_created": len(hash_to_id),
            "movies_created": len(movie_objs),
            "series_created": len(series_objs),
            "episodes_created": created_episodes,
            "cross_links_created": link_count,
            "torrent_field_updates": updates
        }
        logger.info("Import finished summary: %s", summary)
        return summary

# -------------------------
# CLI entrypoint
# -------------------------
def main():
    if len(sys.argv) < 2:
        print("Usage: python tools/imports/import_movies_series_optimized.py /chemin/vers/data_all.json")
        raise SystemExit(1)
    json_file = sys.argv[1]
    res = import_movies_and_series(json_file)
    print("Import finished. Summary:", res)

if __name__ == "__main__":
    main()
