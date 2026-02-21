#!/usr/bin/env python3
"""
tag-no-seed-movies.py

Récupère les films en BDD où latest_torrent_id est NULL, les cherche sur Radarr par titre,
et tagge les films trouvés dans Radarr avec le tag "NOSEED".

Configuration: modifie les variables ci-dessous.
Sortie: JSON unique sur stdout -> liste des actions (taggés / non trouvés / erreurs).
"""

# ==============================
# CONFIGURATION (modifier ici)
# ==============================
RADARR_URL = "http://192.168.10.100:7878"     # ex: http://radarr.local:7878
RADARR_API_KEY = "bf545bb0412540de9d0a6b3cba6cecb1"
HTTP_TIMEOUT = 10.0

# ==============================

import sys
import json
import requests
from pathlib import Path
from typing import List, Dict

# --- rendre le projet importable (fonctionne si le fichier est dans app/ ou à la racine) ---
HERE = Path(__file__).resolve()
PROJECT_ROOT = HERE.parent.parent if HERE.parent.name == "app" else HERE.parent
sys.path.insert(0, str(PROJECT_ROOT))

# imports app
try:
    from app import create_app
    from app.extensions import db
    from app.models.movies import Movie
except Exception as exc:
    print(f"Erreur import app: {exc}", file=sys.stderr)
    sys.exit(2)

HEADERS = {"X-Api-Key": RADARR_API_KEY, "Content-Type": "application/json"}

def get_movies_without_torrent() -> List[Dict]:
    """Retourne la liste des movies DB où latest_torrent_id is NULL."""
    with app.app_context():
        rows = db.session.query(Movie).filter(Movie.latest_torrent_id == None).all()
        return [{"id": r.id, "title": r.title, "radarr_id": r.radarr_id} for r in rows]

def radarr_lookup_by_title(title: str):
    """
    Utilise l'endpoint de lookup Radarr pour chercher par titre.
    (GET /api/v3/movie/lookup?term=...)
    """
    url = f"{RADARR_URL.rstrip('/')}/api/v3/movie/lookup"
    params = {"term": title}
    r = requests.get(url, headers=HEADERS, params=params, timeout=HTTP_TIMEOUT)
    if r.status_code != 200:
        raise RuntimeError(f"lookup failed status={r.status_code} body={r.text}")
    return r.json()  # liste possible de résultats TMDB-like

def radarr_get_all_movies():
    """Récupère tous les films connus par Radarr (GET /api/v3/movie)."""
    url = f"{RADARR_URL.rstrip('/')}/api/v3/movie"
    r = requests.get(url, headers=HEADERS, timeout=HTTP_TIMEOUT)
    if r.status_code != 200:
        raise RuntimeError(f"GET /movie failed status={r.status_code} body={r.text}")
    return r.json()  # liste d'objets films (avec id, tmdbId, title, tags, ...)

def get_or_create_tag(tag_label: str) -> int:
    """
    Vérifie si le tag existe (GET /api/v3/tag). Si non, le crée (POST /api/v3/tag).
    Retourne l'id du tag.
    """
    url = f"{RADARR_URL.rstrip('/')}/api/v3/tag"
    r = requests.get(url, headers=HEADERS, timeout=HTTP_TIMEOUT)
    if r.status_code != 200:
        raise RuntimeError(f"GET /tag failed status={r.status_code} body={r.text}")
    tags = r.json()
    for t in tags:
        if str(t.get("label")).lower() == tag_label.lower():
            return t.get("id")

    # create
    payload = {"label": tag_label}
    r = requests.post(url, headers=HEADERS, json=payload, timeout=HTTP_TIMEOUT)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"POST /tag failed status={r.status_code} body={r.text}")
    return r.json().get("id")

def radarr_get_movie_by_id(movie_id: int):
    url = f"{RADARR_URL.rstrip('/')}/api/v3/movie/{movie_id}"
    r = requests.get(url, headers=HEADERS, timeout=HTTP_TIMEOUT)
    if r.status_code != 200:
        raise RuntimeError(f"GET /movie/{movie_id} failed status={r.status_code} body={r.text}")
    return r.json()

def radarr_update_movie(movie_obj: dict):
    """
    Met à jour le film (PUT /api/v3/movie).
    radarr attend normalement un objet complet; certaines installations acceptent PUT /api/v3/movie/{id}
    Nous utilisons PUT /api/v3/movie pour compatibilité.
    """
    url = f"{RADARR_URL.rstrip('/')}/api/v3/movie"
    r = requests.put(url, headers=HEADERS, json=movie_obj, timeout=HTTP_TIMEOUT)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"PUT /movie failed status={r.status_code} body={r.text}")
    return r.json()

def find_radarr_movie_objects_by_tmdb(tmdb_id: int, all_radarr_movies: List[dict]) -> List[dict]:
    """Filtre la liste radarr pour trouver les objets qui ont tmdbId == tmdb_id."""
    matches = []
    for m in all_radarr_movies:
        if m.get("tmdbId") == tmdb_id:
            matches.append(m)
    return matches

# ---------------------
# Main
# ---------------------
if __name__ == "__main__":
    # create app context once
    try:
        app = create_app()
    except Exception as exc:
        print(json.dumps({"error": f"create_app failed: {exc}"}), file=sys.stderr)
        sys.exit(3)

    results = {"tagged": [], "skipped_not_found": [], "errors": []}

    try:
        with app.app_context():
            # 1) récupère films DB sans latest_torrent_id
            db_movies = db.session.query(Movie).filter(Movie.latest_torrent_id == None).all()
            # si aucun film à traiter, on sort avec JSON vide
            if not db_movies:
                print(json.dumps(results, ensure_ascii=False))
                sys.exit(0)

        # 2) récupère catalogue Radarr (pour matcher tmdbId -> radarr movie id)
        try:
            radarr_movies_catalog = radarr_get_all_movies()
        except Exception as exc:
            print(json.dumps({"error": f"Failed to fetch radarr movie catalog: {exc}"}), file=sys.stderr)
            sys.exit(4)

        # 3) ensure tag exists
        try:
            tag_id = get_or_create_tag("NOSEED")
        except Exception as exc:
            print(json.dumps({"error": f"Failed to get/create tag: {exc}"}), file=sys.stderr)
            sys.exit(5)

        # 4) loop through DB movies and lookup in Radarr
        for m in db_movies:
            title = (m.title or "").strip()
            if not title:
                results["skipped_not_found"].append({"movie_id": m.id, "title": m.title, "reason": "empty title"})
                continue

            try:
                lookup_results = radarr_lookup_by_title(title)
            except Exception as exc:
                results["errors"].append({"movie_id": m.id, "title": title, "error": f"lookup error: {exc}"})
                continue

            if not lookup_results:
                results["skipped_not_found"].append({"movie_id": m.id, "title": title, "reason": "no lookup results"})
                continue

            # lookup_results contient typiquement des objets avec tmdbId
            # pour chaque résultat, on tente de trouver la correspondance dans le catalogue Radarr (pour obtenir radarr movie id)
            tagged_any = False
            for lr in lookup_results:
                tmdb_id = lr.get("tmdbId") or lr.get("tmdbId")
                if not tmdb_id:
                    continue
                matches = find_radarr_movie_objects_by_tmdb(tmdb_id, radarr_movies_catalog)
                if not matches:
                    # pas dans la librairie radarr ; on ignore (peut être juste recherche externe)
                    continue

                for rad in matches:
                    try:
                        # get full radarr movie object to update tags reliably
                        rad_full = radarr_get_movie_by_id(rad.get("id"))
                        current_tags = rad_full.get("tags") or []
                        if tag_id in current_tags:
                            # déjà taggé
                            results["tagged"].append({
                                "movie_db_id": m.id,
                                "title": title,
                                "radarr_movie_id": rad.get("id"),
                                "radarr_title": rad.get("title"),
                                "action": "already_tagged"
                            })
                            tagged_any = True
                            continue

                        # append tag id and update
                        new_tags = list(set(current_tags + [tag_id]))
                        rad_full["tags"] = new_tags

                        # perform update
                        radarr_update_movie(rad_full)

                        results["tagged"].append({
                            "movie_db_id": m.id,
                            "title": title,
                            "radarr_movie_id": rad.get("id"),
                            "radarr_title": rad.get("title"),
                            "action": "tag_added"
                        })
                        tagged_any = True

                    except Exception as exc:
                        results["errors"].append({
                            "movie_db_id": m.id,
                            "title": title,
                            "radarr_movie_id": rad.get("id") if rad.get("id") else None,
                            "error": str(exc)
                        })

            if not tagged_any:
                results["skipped_not_found"].append({"movie_id": m.id, "title": title, "reason": "no matching radarr library movie found from lookup"})

    except Exception as exc:
        results["errors"].append({"fatal": str(exc)})

    # sortie JSON unique
    print(json.dumps(results, indent=2, ensure_ascii=False))
    # erreurs restent aussi dans results["errors"], mais les exceptions critiques ont été writtent sur stderr précédemment.
