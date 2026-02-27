# app/import_full_pipeline.py
"""
Import pipeline that:
1) creates all torrents (parents + cross-seed children)
2) links cross-seeds child.cross_seed_id -> parent.id
3) creates movies and links latest_torrent_id
4) creates series
5) creates episodes and links latest_torrent_id

Run as module from project root:
    python -m app.import_full_pipeline --json /path/to/mycatalog_with_crossseeds_qb.json [--dry-run]
"""
import argparse
import json
import logging
import os
import sys
import uuid
from typing import Any, Dict, List, Optional

# try to use app factory if present
try:
    from app import create_app
except Exception:
    create_app = None

# import repos and db
try:
    from app.repositories.torrents_repo import TorrentsRepo
    from app.repositories.series_repo import SeriesRepo
    from app.repositories.episodes_repo import EpisodesRepo
    from app.repositories.movies_repo import MoviesRepo
    from app.extensions import db
except Exception as e:
    print("Failed to import application modules. Make sure to run from project root as a module (python -m app.import_full_pipeline).")
    raise

logger = logging.getLogger("import_full_pipeline")
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [import_full_pipeline] %(message)s"))
logger.addHandler(handler)
logger.setLevel(logging.INFO)


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
DEFAULT_JSON = os.path.join(ROOT_DIR, "mycatalog_with_crossseeds_qb.json")


# ---------- helpers ----------

def ensure_hash(h: Optional[str]) -> str:
    """
    Normalize a hash if present, otherwise produce a placeholder non-null hash.
    """
    if h and isinstance(h, str) and h.strip():
        return h.strip().lower()
    return f"missing-{uuid.uuid4().hex}"


def parse_torrent_dict(t: Any) -> Dict[str, Any]:
    """
    Normalize common keys to canonical ones.
    Returns dict with keys: info_hash, torrent_name, indexer, episodes (list), cross_seed (list), weight
    """
    if not isinstance(t, dict):
        return {
            "info_hash": None,
            "torrent_name": str(t) if t is not None else None,
            "indexer": None,
            "episodes": [],
            "cross_seed": [],
            "weight": None,
        }
    info_hash = t.get("info_hash") or t.get("hash") or t.get("torrent_hash") or t.get("infoHash")
    torrent_name = t.get("torrent_name") or t.get("torrent") or t.get("name") or t.get("title")
    indexer = t.get("indexer") or t.get("indexer_name")
    episodes = t.get("episodes") or t.get("episode") or []
    cross_seed = t.get("cross_seed") or t.get("cross_seeds") or t.get("children") or []
    weight = t.get("weight")
    return {
        "info_hash": info_hash,
        "torrent_name": torrent_name,
        "indexer": indexer,
        "episodes": episodes,
        "cross_seed": cross_seed,
        "weight": weight,
    }


def safe_list(v: Any) -> List[Any]:
    if v is None:
        return []
    if isinstance(v, list):
        return v
    if isinstance(v, dict):
        # some JSONs embed a dict where list expected => wrap to single element
        return [v]
    # int/str -> wrap too
    return [v]


# ---------- main pipeline ----------

def run_import(json_path: str, dry_run: bool = False):
    logger.info("Starting pipeline import for: %s (dry_run=%s)", json_path, dry_run)
    if not os.path.exists(json_path):
        logger.error("JSON file not found: %s", json_path)
        return

    with open(json_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    torrents_repo = TorrentsRepo()
    series_repo = SeriesRepo()
    episodes_repo = EpisodesRepo()
    movies_repo = MoviesRepo()

    # maps
    hash_to_torrent = {}   # normalized_hash -> Torrents model
    movie_map = {}         # radarr_id (str) -> Movie model
    series_map = {}        # sonarr_id (str) -> Series model

    # ---------- Step 1: create all torrents (parents + children) ----------
    logger.info("STEP 1: Create all torrents (parents + cross-seed entries)")
    # iterate two high-level categories we expect (but be general)
    # top-level structure appears to be: {"films": {id: [torrents]}, "series_anime": {id: [torrents]}, ...}
    # So we must iterate nested dicts
    def iter_torrent_objects(top_val):
        """
        Yields torrent dicts found under a top-level value which may be:
          - dict(id -> list_of_torrents)
          - list of torrents
          - single dict
        """
        if isinstance(top_val, dict):
            # if the dict maps ids to lists -> iterate values
            # if values are lists -> iterate each item
            for v in top_val.values():
                if isinstance(v, list):
                    for it in v:
                        yield it
                elif isinstance(v, dict):
                    yield v
                else:
                    yield v
            return
        if isinstance(top_val, list):
            for item in top_val:
                yield item
            return
        if top_val is not None:
            yield top_val

    # find all torrent objects and cross-seed objects and create Torrent rows for each unique hash
    for top_key, top_val in data.items():
        for t_raw in iter_torrent_objects(top_val):
            parsed = parse_torrent_dict(t_raw)
            h = ensure_hash(parsed["info_hash"])
            name = parsed["torrent_name"]
            # create/get torrent
            if h not in hash_to_torrent:
                try:
                    if not dry_run:
                        t_model = torrents_repo.create(hashval=h, name=(name.strip() if isinstance(name, str) else None))
                    else:
                        # dry-run: try to fetch if exists, else create fake struct with id=None
                        t_model = torrents_repo.get_by_hash(h) or type("Fake", (), {"id": None, "hash": h, "name": name})
                except Exception as e:
                    logger.exception("Error creating/getting torrent for hash=%s name=%r: %s", h, name, e)
                    t_model = torrents_repo.get_by_hash(h)
                if t_model:
                    hash_to_torrent[h] = t_model
            # ensure cross_seed children are also created
            cs_list = safe_list(parsed.get("cross_seed"))
            for cs in cs_list:
                if isinstance(cs, dict):
                    child_hash = ensure_hash(cs.get("hash") or cs.get("info_hash"))
                    child_name = cs.get("torrent_name") or cs.get("torrent") or None
                else:
                    # cs might be a string or other
                    child_hash = ensure_hash(cs if isinstance(cs, str) else None)
                    child_name = None
                if child_hash not in hash_to_torrent:
                    try:
                        if not dry_run:
                            child_model = torrents_repo.create(hashval=child_hash, name=(child_name.strip() if isinstance(child_name, str) else None))
                        else:
                            child_model = torrents_repo.get_by_hash(child_hash) or type("Fake", (), {"id": None, "hash": child_hash, "name": child_name})
                    except Exception as e:
                        logger.exception("Error creating child torrent %s: %s", child_hash, e)
                        child_model = torrents_repo.get_by_hash(child_hash)
                    if child_model:
                        hash_to_torrent[child_hash] = child_model

    logger.info("STEP 1 done: found %d unique hashes (including children)", len(hash_to_torrent))

    # ---------- Step 2: link cross-seeds to parent ----------
    logger.info("STEP 2: Link cross-seed children to their parent torrents")
    for top_key, top_val in data.items():
        for t_raw in iter_torrent_objects(top_val):
            parsed = parse_torrent_dict(t_raw)
            parent_hash = ensure_hash(parsed["info_hash"])
            parent_model = hash_to_torrent.get(parent_hash)
            if parent_model is None:
                logger.warning("Parent torrent not found for hash=%s (top_key=%s). Skipping cross-link for this item.", parent_hash, top_key)
                continue
            cs_list = safe_list(parsed.get("cross_seed"))
            for cs in cs_list:
                if isinstance(cs, dict):
                    child_hash = ensure_hash(cs.get("hash") or cs.get("info_hash"))
                else:
                    child_hash = ensure_hash(cs if isinstance(cs, str) else None)
                child_model = hash_to_torrent.get(child_hash) or torrents_repo.get_by_hash(child_hash)
                if child_model is None:
                    logger.warning("Child torrent not present for hash=%s — skipping linking", child_hash)
                    continue
                # set cross_seed_id on child to parent's id
                if getattr(child_model, "cross_seed_id", None) != getattr(parent_model, "id", None):
                    child_model.cross_seed_id = getattr(parent_model, "id", None)
                    if not dry_run:
                        db.session.add(child_model)
                        try:
                            db.session.commit()
                            logger.info("Linked child id=%s -> parent id=%s", getattr(child_model, "id", None), getattr(parent_model, "id", None))
                        except Exception:
                            logger.exception("Failed to commit cross-seed link for child=%s parent=%s", child_hash, parent_hash)
                            try:
                                db.session.rollback()
                            except Exception:
                                pass
                    else:
                        logger.info("DRY RUN: Would link child hash=%s -> parent hash=%s", child_hash, parent_hash)

    # ---------- Step 3: create movies and attach latest_torrent ----------
    logger.info("STEP 3: Create Movie rows and attach latest_torrent_id (films bucket)")

    films_bucket = data.get("films") or {}
    # films_bucket is dict: radarr_id -> list of torrents
    for radarr_id, torrent_list in films_bucket.items():
        # find a parent torrent in this bucket (prefer first with valid info_hash)
        chosen_parent = None
        if isinstance(torrent_list, list):
            for t_raw in torrent_list:
                parsed = parse_torrent_dict(t_raw)
                h = ensure_hash(parsed["info_hash"])
                chosen_parent = hash_to_torrent.get(h)
                if chosen_parent:
                    break
        # create or update movie
        movie = movies_repo.get_by_radarr_id(str(radarr_id))
        if movie is None:
            if not dry_run:
                movie = movies_repo.create(radarr_id=str(radarr_id), title=None, latest_torrent_id=(getattr(chosen_parent, "id", None) if chosen_parent else None))
                logger.info("Created Movie radarr_id=%s -> id=%s latest_torrent=%s", radarr_id, getattr(movie, "id", None), getattr(chosen_parent, "id", None))
            else:
                logger.info("DRY RUN: Would create Movie radarr_id=%s latest_torrent=%s", radarr_id, getattr(chosen_parent, "id", None))
        else:
            # update latest_torrent_id if found
            if chosen_parent:
                movie.latest_torrent_id = getattr(chosen_parent, "id", None)
                if not dry_run:
                    movies_repo.save(movie)
                    logger.info("Updated Movie id=%s latest_torrent=%s", getattr(movie, "id", None), getattr(chosen_parent, "id", None))
                else:
                    logger.info("DRY RUN: Would update Movie id=%s latest_torrent=%s", getattr(movie, "id", None), getattr(chosen_parent, "id", None))

    # ---------- Step 4: create all series ----------
    logger.info("STEP 4: Create Series rows (series_anime and others that have episodes)")
    # find all top-level keys that are series-like (series_anime or any top key where values contain episodes)
    for top_key, top_val in data.items():
        # top_val could be dict(id->list)
        if isinstance(top_val, dict):
            # iterate inner id keys
            for inner_id, t_list in top_val.items():
                # detect if inner t_list has episodes
                if isinstance(t_list, list) and any((parse_torrent_dict(x).get("episodes")) for x in t_list):
                    # create series for this inner_id
                    if str(inner_id) not in series_map:
                        s = series_repo.get_by_sonarr_id(str(inner_id))
                        if s is None:
                            if not dry_run:
                                s = series_repo.create(sonarr_id=str(inner_id), title=None)
                                logger.info("Created Series sonarr_id=%s -> id=%s", inner_id, getattr(s, "id", None))
                            else:
                                logger.info("DRY RUN: Would create Series sonarr_id=%s", inner_id)
                                s = type("FakeSeries", (), {"id": None})
                        series_map[str(inner_id)] = s
        else:
            # other shapes: skip
            continue

    # ---------- Step 5: create episodes for each series and link latest_torrent_id ----------
    logger.info("STEP 5: Create Episodes and link latest_torrent_id")
    # For each series id in series_map, find its torrent list and create episodes
    series_bucket = data.get("series_anime") or {}
    # series_bucket is like: { "207": [ {torrent}, ... ], ... }
    for sonarr_id, torrent_list in series_bucket.items():
        s_model = series_map.get(str(sonarr_id)) or series_repo.get_by_sonarr_id(str(sonarr_id))
        if s_model is None:
            logger.warning("No Series model found for sonarr_id=%s. Skipping episodes.", sonarr_id)
            continue
        if not isinstance(torrent_list, list):
            continue
        for t_raw in torrent_list:
            parsed = parse_torrent_dict(t_raw)
            parent_hash = ensure_hash(parsed["info_hash"])
            parent_model = hash_to_torrent.get(parent_hash)
            episodes = safe_list(parsed.get("episodes"))
            # episodes might include dicts with season/episode or ints etc. We'll try to be permissive:
            for ep in episodes:
                # normalize
                if isinstance(ep, dict):
                    season = ep.get("season")
                    episode_number = ep.get("episode") or ep.get("episode_number") or ep.get("ep")
                    title = ep.get("title") or ep.get("episode_title") or None
                elif isinstance(ep, int):
                    # if torrent-level season exists, use it; else skip creation of season unknown
                    season = parsed.get("season") if isinstance(parsed.get("season"), int) else None
                    episode_number = int(ep)
                    title = None
                else:
                    logger.warning("Episode entry for series %s is not dict/int: %r. Skipping this episode item.", sonarr_id, ep)
                    continue

                if season is None or episode_number is None:
                    logger.warning("Missing season/episode for series %s entry: %r. Skipping.", sonarr_id, ep)
                    continue

                # create or update episode
                existing = episodes_repo.get_by_series_season_episode(s_model.id, season, episode_number)
                if existing is None:
                    if not dry_run:
                        new_ep = episodes_repo.create(
                            serie_id=s_model.id,
                            title=title,
                            season=season,
                            episode=episode_number,
                            latest_torrent_id=getattr(parent_model, "id", None)
                        )
                        logger.info("Created Episode series_id=%s S%02dE%02d -> id=%s latest_torrent=%s", s_model.id, int(season), int(episode_number), getattr(new_ep, "id", None), getattr(parent_model, "id", None))
                    else:
                        logger.info("DRY RUN: Would create Episode series_id=%s S%02dE%02d latest_torrent=%s", getattr(s_model,'id',None), int(season), int(episode_number), getattr(parent_model, "id", None))
                else:
                    # update latest_torrent_id if present and different
                    if parent_model and existing.latest_torrent_id != getattr(parent_model, "id", None):
                        existing.latest_torrent_id = getattr(parent_model, "id", None)
                        if not dry_run:
                            episodes_repo.save(existing)
                            logger.info("Updated Episode id=%s latest_torrent=%s", getattr(existing, "id", None), getattr(parent_model, "id", None))
                        else:
                            logger.info("DRY RUN: Would update Episode id=%s latest_torrent=%s", getattr(existing, "id", None), getattr(parent_model, "id", None))

    logger.info("Import pipeline finished.")


# ---------- CLI entry ----------

def main():
    parser = argparse.ArgumentParser(description="Full import pipeline for mycatalog JSON")
    parser.add_argument("--json", "-j", default=DEFAULT_JSON, help="Path to JSON file")
    parser.add_argument("--dry-run", action="store_true", help="Do not perform DB commits; dry run")
    args = parser.parse_args()

    if create_app:
        app = create_app()
        with app.app_context():
            run_import(args.json, dry_run=args.dry_run)
    else:
        try:
            from flask import current_app
            with current_app.app_context():
                run_import(args.json, dry_run=args.dry_run)
        except Exception as e:
            logger.error("No create_app() and no current_app available. Run in flask shell or add create_app(). Error: %s", e)


if __name__ == "__main__":
    main()