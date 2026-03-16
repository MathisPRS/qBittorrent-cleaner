#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
radarr_reseed_batch.py

Workflow:
 - Récupère le tag NOSEED (créé s'il n'existe pas).
 - Récupère la liste des films dans Radarr qui ont ce tag.
 - Prend jusqu'à N (default 10) films.
 - Pour chaque film :
     1) Supprime les moviefile(s) associés via DELETE /api/v3/moviefile/{id} (supprime le fichier sur disque si Radarr est configuré ainsi).
     2) Lance une recherche manuelle / rescan pour que Radarr ré-enfilele le téléchargement.
     3) Enlève le tag NOSEED du film (untag).
 - Résumé JSON sur stdout.
Notes:
 - Placer à la racine du projet (même niveau que `app/`) et exécuter depuis la racine.
 - Testez d'abord avec --dry-run.
References: Radarr API (command, moviefile, movie). :contentReference[oaicite:1]{index=1}
"""

import sys
import json
import requests
from pathlib import Path
from typing import List, Dict, Set, Optional
import argparse

# ==============================
# CONFIGURATION (modifier ici)
# ==============================
RADARR_URL = "http://192.168.10.100:7878"
RADARR_API_KEY = "bf545bb0412540de9d0a6b3cba6cecb1"
HTTP_TIMEOUT = 10.0
TAG_LABEL = "NOSEED"
DEFAULT_BATCH_SIZE = 10
# ==============================

HERE = Path(__file__).resolve()
PROJECT_ROOT = HERE.parent.parent if HERE.parent.name == "app" else HERE.parent
sys.path.insert(0, str(PROJECT_ROOT))

# imports app
try:
    from app import create_app
except Exception as exc:
    print(json.dumps({"error": f"Erreur import app: {exc}"}), file=sys.stderr)
    sys.exit(2)

HEADERS = {"X-Api-Key": RADARR_API_KEY, "Content-Type": "application/json"}


def radarr_request(method: str, path: str, **kwargs) -> requests.Response:
    url = f"{RADARR_URL.rstrip('/')}{path}"
    fn = getattr(requests, method.lower())
    return fn(url, headers=HEADERS, timeout=HTTP_TIMEOUT, **kwargs)


def ensure_tag(tag_label: str) -> int:
    """Get tag id for label, create if missing."""
    r = radarr_request("get", "/api/v3/tag")
    if r.status_code != 200:
        raise RuntimeError(f"GET /tag failed status={r.status_code} body={r.text}")
    tags = r.json()
    for t in tags:
        if str(t.get("label", "")).lower() == tag_label.lower():
            return t.get("id")
    # create
    payload = {"label": tag_label}
    r = radarr_request("post", "/api/v3/tag", json=payload)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"POST /tag failed status={r.status_code} body={r.text}")
    return r.json().get("id")


def get_all_radarr_movies() -> List[dict]:
    r = radarr_request("get", "/api/v3/movie")
    if r.status_code != 200:
        raise RuntimeError(f"GET /movie failed status={r.status_code} body={r.text}")
    return r.json()


def get_moviefile_for_movie(movie_id: int) -> List[dict]:
    """
    Récupère les moviefiles associés au film.
    Essaie GET /api/v3/moviefile?movieId=... si supporté, sinon GET /api/v3/moviefile et filtre.
    """
    # try query param
    r = radarr_request("get", f"/api/v3/moviefile", params={"movieId": movie_id})
    if r.status_code == 200:
        return r.json()
    # fallback to full list and filter
    r2 = radarr_request("get", "/api/v3/moviefile")
    if r2.status_code != 200:
        raise RuntimeError(f"GET /moviefile failed status={r2.status_code} body={r2.text}")
    files = r2.json()
    return [f for f in files if f.get("movieId") == movie_id]


def delete_moviefile(moviefile_id: int, dry_run: bool = False) -> None:
    """
    Supprime le moviefile via DELETE /api/v3/moviefile/{id}.
    Selon la config Radarr, cela supprime le fichier disque (ou non).
    """
    if dry_run:
        return
    r = radarr_request("delete", f"/api/v3/moviefile/{moviefile_id}")
    if r.status_code not in (200, 204):
        raise RuntimeError(f"DELETE /moviefile/{moviefile_id} failed status={r.status_code} body={r.text}")


def trigger_manual_search(movie_id: int, dry_run: bool = False) -> dict:
    """
    Tente de déclencher la recherche manuelle pour le film.
    Essaie plusieurs payloads communs (varie selon versions).
    Retourne le JSON réponse du /api/v3/command POST quand OK.
    """
    if dry_run:
        return {"dry_run": True}

    # 1) Try MoviesSearch with movieIds list
    payloads = [
        {"name": "MoviesSearch", "movieIds": [movie_id]},
        {"name": "ManualSearch", "movieId": movie_id},
        {"name": "SearchForMovie", "movieId": movie_id},  # fallback try
    ]
    last_exc = None
    for payload in payloads:
        r = radarr_request("post", "/api/v3/command", json=payload)
        if r.status_code in (200, 201):
            try:
                return r.json()
            except Exception:
                return {"status_code": r.status_code, "text": r.text}
        # collect last error
        last_exc = (r.status_code, r.text)
    raise RuntimeError(f"All command payloads failed. Last: {last_exc}")


def update_movie_tags(movie_obj: dict, tag_id: int, remove: bool = True, dry_run: bool = False) -> dict:
    """
    Ajoute/retire le tag_id de movie_obj['tags'] et PUT /api/v3/movie.
    remove=True -> retire; remove=False -> ajoute.
    """
    tags = movie_obj.get("tags") or []
    if remove:
        if tag_id not in tags:
            return {"action": "no_change", "movieId": movie_obj.get("id")}
        new_tags = [t for t in tags if t != tag_id]
    else:
        if tag_id in tags:
            return {"action": "no_change", "movieId": movie_obj.get("id")}
        new_tags = list(dict.fromkeys(tags + [tag_id]))
    movie_obj["tags"] = new_tags
    if dry_run:
        return {"action": "dry_run_put", "movieId": movie_obj.get("id"), "new_tags": new_tags}
    r = radarr_request("put", "/api/v3/movie", json=movie_obj)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"PUT /movie failed status={r.status_code} body={r.text}")
    return r.json()


def main(batch_size: int, dry_run: bool = False):
    results = {
        "selected": [],
        "deleted_files": [],
        "searches_triggered": [],
        "untagged": [],
        "skipped_no_files": [],
        "errors": [],
    }

    # create app context (used only to ensure proper env if needed)
    try:
        app = create_app()
    except Exception as exc:
        print(json.dumps({"error": f"create_app failed: {exc}"}), file=sys.stderr)
        sys.exit(2)

    # ensure tag exists
    try:
        tag_id = ensure_tag(TAG_LABEL)
    except Exception as exc:
        print(json.dumps({"error": f"Failed to get/create tag: {exc}"}), file=sys.stderr)
        sys.exit(3)

    # fetch radarr catalog and filter to movies that have the tag
    try:
        all_movies = get_all_radarr_movies()
    except Exception as exc:
        print(json.dumps({"error": f"Failed to fetch radarr movie catalog: {exc}"}), file=sys.stderr)
        sys.exit(4)

    movies_with_tag = [m for m in all_movies if tag_id in (m.get("tags") or [])]

    # take up to batch_size
    to_process = movies_with_tag[:batch_size]

    for m in to_process:
        mid = m.get("id")
        title = m.get("title")
        results["selected"].append({"radarr_movie_id": mid, "title": title})
        try:
            # 1) get moviefiles
            files = get_moviefile_for_movie(mid)
            if not files:
                results["skipped_no_files"].append({"radarr_movie_id": mid, "title": title, "reason": "no moviefile found"})
            else:
                for f in files:
                    fid = f.get("id")
                    try:
                        delete_moviefile(fid, dry_run=dry_run)
                        results["deleted_files"].append({"radarr_movie_id": mid, "moviefile_id": fid, "path": f.get("path")})
                    except Exception as exc:
                        results["errors"].append({"radarr_movie_id": mid, "moviefile_id": fid, "error": str(exc)})
                        # continue to next file; do not abort whole batch

            # 2) trigger manual search / re-download
            try:
                cmd_resp = trigger_manual_search(mid, dry_run=dry_run)
                results["searches_triggered"].append({"radarr_movie_id": mid, "title": title, "command_response": cmd_resp})
            except Exception as exc:
                results["errors"].append({"radarr_movie_id": mid, "step": "trigger_search", "error": str(exc)})

            # 3) untag (remove NOSEED)
            try:
                # fetch full movie object before updating (to ensure full payload)
                rfull = radarr_request("get", f"/api/v3/movie/{mid}")
                if rfull.status_code != 200:
                    raise RuntimeError(f"GET /movie/{mid} failed status={rfull.status_code} body={rfull.text}")
                movie_obj = rfull.json()
                up = update_movie_tags(movie_obj, tag_id, remove=True, dry_run=dry_run)
                results["untagged"].append({"radarr_movie_id": mid, "title": title, "result": up})
            except Exception as exc:
                results["errors"].append({"radarr_movie_id": mid, "step": "untag", "error": str(exc)})

        except Exception as exc:
            results["errors"].append({"radarr_movie_id": mid, "title": title, "error": str(exc)})

    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch reseed for NOSEED-tagged movies in Radarr.")
    parser.add_argument("--batch", "-n", type=int, default=DEFAULT_BATCH_SIZE, help="Number of movies to process (default 10)")
    parser.add_argument("--dry-run", action="store_true", help="Do not perform destructive actions; only simulate")
    args = parser.parse_args()
    main(batch_size=args.batch, dry_run=args.dry_run)
