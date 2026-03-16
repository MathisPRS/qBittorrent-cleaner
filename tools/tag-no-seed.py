#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tag-no-seed-old-improved.py

Ancien workflow (amélioré, plus de logs) :
1) Retire le tag NOSEED de tous les films dans Radarr (log à chaque untag).
2) Récupère la liste des films en base (latest_hash != NULL ou fallback latest_torrent_id).
3) Récupère la liste complète Radarr, calcule quels films sont "downloaded & available".
4) Calcule la différence : downloaded_total - in_base -> nombre attendu à tagger.
5) Tag uniquement les films downloaded & available AND absents de la BDD (NOSEED).
6) Log détaillé pour chaque action et erreurs. Résultat JSON imprimé à la fin.

Usage:
  python3 tag-no-seed-old-improved.py [--dry-run] [--limit N]

Placez le script à la racine du projet (même niveau que app/).
"""

import sys
import json
import requests
from pathlib import Path
from typing import List, Dict, Set
import argparse

# ==============================
# CONFIGURATION (modifier ici)
# ==============================
RADARR_URL = "http://192.168.10.100:7878"
RADARR_API_KEY = "bf545bb0412540de9d0a6b3cba6cecb1"
HTTP_TIMEOUT = 10.0
TAG_LABEL = "NOSEED"
# ==============================

HERE = Path(__file__).resolve()
PROJECT_ROOT = HERE.parent.parent if HERE.parent.name == "app" else HERE.parent
sys.path.insert(0, str(PROJECT_ROOT))

# imports app (on suppose que create_app existe)
try:
    from app import create_app
    from app.extensions import db
    from app.models.movies import Movie
except Exception as exc:
    print(json.dumps({"error": f"Erreur import app: {exc}"}), file=sys.stderr)
    sys.exit(2)

HEADERS = {"X-Api-Key": RADARR_API_KEY, "Content-Type": "application/json"}


def radarr_request(method: str, path: str, **kwargs) -> requests.Response:
    url = f"{RADARR_URL.rstrip('/')}{path}"
    fn = getattr(requests, method.lower())
    return fn(url, headers=HEADERS, timeout=HTTP_TIMEOUT, **kwargs)


def get_or_create_tag(tag_label: str) -> int:
    r = radarr_request("get", "/api/v3/tag")
    if r.status_code != 200:
        raise RuntimeError(f"GET /tag failed status={r.status_code} body={r.text}")
    tags = r.json()
    for t in tags:
        if str(t.get("label", "")).lower() == tag_label.lower():
            return t.get("id")
    r2 = radarr_request("post", "/api/v3/tag", json={"label": tag_label})
    if r2.status_code not in (200, 201):
        raise RuntimeError(f"POST /tag failed status={r2.status_code} body={r2.text}")
    return r2.json().get("id")


def radarr_get_all_movies() -> List[dict]:
    r = radarr_request("get", "/api/v3/movie")
    if r.status_code != 200:
        raise RuntimeError(f"GET /movie failed status={r.status_code} body={r.text}")
    return r.json()


def radarr_get_movie_by_id(movie_id: int) -> dict:
    r = radarr_request("get", f"/api/v3/movie/{movie_id}")
    if r.status_code != 200:
        raise RuntimeError(f"GET /movie/{movie_id} failed status={r.status_code} body={r.text}")
    return r.json()


def radarr_update_movie(movie_obj: dict):
    r = radarr_request("put", "/api/v3/movie", json=movie_obj)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"PUT /movie failed status={r.status_code} body={r.text}")
    return r.json()


def radarr_get_moviefiles_for_movie(movie_id: int) -> List[dict]:
    # try by movieId query first
    r = radarr_request("get", "/api/v3/moviefile", params={"movieId": movie_id})
    if r.status_code == 200:
        return r.json()
    # fallback to full list filter
    r2 = radarr_request("get", "/api/v3/moviefile")
    if r2.status_code != 200:
        raise RuntimeError(f"GET /moviefile failed status={r2.status_code} body={r2.text}")
    return [mf for mf in r2.json() if mf.get("movieId") == movie_id]


def radarr_movie_has_file(movie_obj: dict) -> bool:
    # prefer hasFile flag if present
    if "hasFile" in movie_obj:
        return bool(movie_obj.get("hasFile"))
    # otherwise check moviefile endpoint
    try:
        mfs = radarr_get_moviefiles_for_movie(movie_obj.get("id"))
        return len(mfs) > 0
    except Exception:
        # en cas d'erreur d'API, considérer False (plus sûr)
        return False


def collect_db_radarr_ids(app) -> Set[int]:
    """Récupère set des radarr_id en BDD pour films considérés 'in base' (latest_hash != NULL fallback latest_torrent_id)."""
    with app.app_context():
        sample = db.session.query(Movie).limit(1).first()
        if sample is None:
            return set()
        if hasattr(sample, "latest_hash"):
            rows = db.session.query(Movie).filter(getattr(Movie, "latest_hash") != None).all()
        elif hasattr(sample, "latest_torrent_id"):
            rows = db.session.query(Movie).filter(getattr(Movie, "latest_torrent_id") != None).all()
        else:
            # fallback: any with radarr_id not null
            rows = db.session.query(Movie).filter(getattr(Movie, "radarr_id") != None).all()
        radarr_ids = set()
        for r in rows:
            try:
                rid = getattr(r, "radarr_id", None)
                if rid is not None:
                    radarr_ids.add(int(rid))
            except Exception:
                continue
        return radarr_ids


def remove_tag_from_all_movies(tag_id: int, radarr_catalog: List[dict], results: dict, dry_run: bool = False):
    """Retire tag_id de tous les films qui l'ont — log à chaque untag."""
    for short in radarr_catalog:
        mid = short.get("id")
        try:
            full = radarr_get_movie_by_id(mid)
        except Exception as exc:
            results["errors"].append({"action": "get_movie_for_untag", "radarr_movie_id": mid, "error": str(exc)})
            print(f"[WARN] impossible de récupérer movie id={mid} pour untag: {exc}")
            continue
        tags = full.get("tags") or []
        if tag_id in tags:
            print(f"[UNTAG] movie id={mid} title='{full.get('title')}' -> removal of tag id={tag_id}")
            results["untagged_logs"].append({"radarr_movie_id": mid, "title": full.get("title")})
            if not dry_run:
                try:
                    new_tags = [t for t in tags if t != tag_id]
                    full["tags"] = new_tags
                    radarr_update_movie(full)
                except Exception as exc:
                    results["errors"].append({"action": "untag_put", "radarr_movie_id": mid, "error": str(exc)})
                    print(f"[ERROR] failed to PUT movie {mid} removing tag: {exc}")


def tag_movies_by_ids(ids_to_tag: Set[int], radarr_map: Dict[int, dict], tag_id: int, results: dict, dry_run: bool = False):
    """Tag each radarr movie (by id) with tag_id, only if present in radarr_map and hasFile==True."""
    for rid in sorted(ids_to_tag):
        short = radarr_map.get(rid)
        if not short:
            results["not_found_in_radarr"].append({"radarr_movie_id": rid})
            print(f"[SKIP] radarr id={rid} not found in Radarr catalog snapshot -> logged as not_found_in_radarr")
            continue
        try:
            full = radarr_get_movie_by_id(rid)
        except Exception as exc:
            results["errors"].append({"action": "get_movie_before_tag", "radarr_movie_id": rid, "error": str(exc)})
            print(f"[ERROR] cannot fetch full radarr movie id={rid} to tag: {exc}")
            continue

        # confirm file present
        if not radarr_movie_has_file(full):
            results["skipped_not_downloaded"].append({"radarr_movie_id": rid, "title": full.get("title")})
            print(f"[SKIP] movie id={rid} title='{full.get('title')}' not downloaded/available -> not tagging")
            continue

        tags = full.get("tags") or []
        if tag_id in tags:
            results["already_tagged"].append({"radarr_movie_id": rid, "title": full.get("title")})
            print(f"[INFO] movie id={rid} title='{full.get('title')}' already has tag -> skipping")
            continue

        print(f"[TAG] adding tag id={tag_id} to movie id={rid} title='{full.get('title')}'")
        if not dry_run:
            try:
                full["tags"] = list(dict.fromkeys(tags + [tag_id]))
                radarr_update_movie(full)
                results["tagged"].append({"radarr_movie_id": rid, "title": full.get("title"), "action": "tag_added"})
            except Exception as exc:
                results["errors"].append({"action": "put_tag", "radarr_movie_id": rid, "error": str(exc)})
                print(f"[ERROR] failed to add tag for movie id={rid}: {exc}")
        else:
            results["tagged"].append({"radarr_movie_id": rid, "title": full.get("title"), "action": "dry_run_tag"})


def main(dry_run: bool = False, limit: int = None):
    results = {
        "untagged_logs": [],
        "db_count": 0,
        "downloaded_count": 0,
        "to_tag_expected": 0,
        "tagged": [],
        "already_tagged": [],
        "skipped_not_downloaded": [],
        "not_found_in_radarr": [],
        "errors": []
    }

    # create app
    try:
        app = create_app()
    except Exception as exc:
        print(json.dumps({"error": f"create_app failed: {exc}"}), file=sys.stderr)
        sys.exit(2)

    # 1) fetch radarr catalog
    try:
        radarr_catalog = radarr_get_all_movies()
    except Exception as exc:
        print(json.dumps({"error": f"Failed to fetch radarr movie catalog: {exc}"}), file=sys.stderr)
        sys.exit(4)

    # map id -> short obj
    radarr_map = {}
    for m in radarr_catalog:
        try:
            radarr_map[int(m.get("id"))] = m
        except Exception:
            continue

    # 2) ensure tag exists
    try:
        tag_id = get_or_create_tag(TAG_LABEL)
    except Exception as exc:
        print(json.dumps({"error": f"Failed to get/create tag: {exc}"}), file=sys.stderr)
        sys.exit(5)

    # 3) remove tag from everyone (untag) and log each untag
    print("=== Removing NOSEED tag from all Radarr movies (logging each untag) ===")
    remove_tag_from_all_movies(tag_id, radarr_catalog, results, dry_run=dry_run)
    print("=== Finished untag pass ===")

    # 4) collect DB radarr ids (films considered present in DB)
    try:
        db_radarr_ids = collect_db_radarr_ids(app)
    except Exception as exc:
        print(json.dumps({"error": f"Failed to fetch radarr ids from DB: {exc}"}), file=sys.stderr)
        sys.exit(6)
    results["db_count"] = len(db_radarr_ids)
    print(f"[INFO] Number of films in DB (with latest_hash / latest_torrent_id): {results['db_count']}")

    # 5) determine downloaded & available movies in radarr
    downloaded_ids = set()
    print("[INFO] Scanning Radarr catalog for downloaded/available movies (hasFile or moviefile present)...")
    for mid, short in radarr_map.items():
        try:
            if radarr_movie_has_file(short):
                downloaded_ids.add(mid)
        except Exception as exc:
            results["errors"].append({"action": "check_has_file", "radarr_movie_id": mid, "error": str(exc)})

    results["downloaded_count"] = len(downloaded_ids)
    print(f"[INFO] Number of downloaded & available movies in Radarr: {results['downloaded_count']}")

    # 6) expected to tag = downloaded_total - in_base (but floor at 0)
    expected_to_tag = max(0, results["downloaded_count"] - results["db_count"])
    results["to_tag_expected"] = expected_to_tag
    print(f"[INFO] Expected number to tag NOSEED = downloaded_total - in_base = {results['downloaded_count']} - {results['db_count']} = {expected_to_tag}")

    # 7) compute actual to_tag set = downloaded_ids - db_radarr_ids
    to_tag_set = downloaded_ids.difference(db_radarr_ids)
    if limit:
        to_tag_list = list(to_tag_set)[:limit]
        to_tag_set = set(to_tag_list)
        print(f"[INFO] Limiting to first {len(to_tag_set)} items (limit={limit})")
    print(f"[INFO] Actual candidates to tag (count={len(to_tag_set)}): {sorted(list(to_tag_set))}")

    # 8) tag those movies
    tag_movies_by_ids(to_tag_set, radarr_map, tag_id, results, dry_run=dry_run)

    # 9) final prints + JSON
    print("\n=== Summary ===")
    print(f"DB films (in base)           : {results['db_count']}")
    print(f"Downloaded & available (radarr): {results['downloaded_count']}")
    print(f"Expected to tag (diff)       : {results['to_tag_expected']}")
    print(f"Actually tagged (count)      : {len(results['tagged'])}")
    print(f"Already tagged (skipped)     : {len(results['already_tagged'])}")
    print(f"Skipped not downloaded       : {len(results['skipped_not_downloaded'])}")
    print(f"Not found in radarr snapshot : {len(results['not_found_in_radarr'])}")
    print(f"Errors                       : {len(results['errors'])}")

    # print result JSON to stdout (also human-readable printed above)
    print("\nJSON result:")
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ancien script amélioré : untag all then tag NOSEED for downloaded-but-not-in-db movies.")
    parser.add_argument("--dry-run", action="store_true", help="Do not perform changes (simulate only)")
    parser.add_argument("--limit", type=int, default=None, help="Optional limit on how many movies to tag (for tests)")
    args = parser.parse_args()
    main(dry_run=args.dry_run, limit=args.limit)
