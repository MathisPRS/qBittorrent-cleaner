#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
radarr_qb_single_crossseed.py

Sortie unique: radarr_qb_single.json

Pour chaque film Radarr :
 - id_radarr
 - title
 - torrents: liste des torrents HISTORIQUES qui sont ENCORE présents dans qB
    - hash
    - qb_name
    - qb_indexer
    - cross_seed: [ { hash, qb_name, qb_indexer }, ... ]  (children whose category contains 'cross' and name exactly matches)

Instructions:
 - Remplace BASE_URL / API_KEY / VAR_QBIT_* avant exécution.
"""
import requests
import time
import json
import re
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Set
from collections import defaultdict

# ---------------------------
# CONFIG (EDIT)
# ---------------------------
BASE_URL = "http://192.168.10.100:7878"        # ex: "http://192.168.10.50:7878"
API_KEY = "bf545bb0412540de9d0a6b3cba6cecb1"  # <-- remplace
PAGE_SIZE = 200
INCLUDE_MOVIE = True
SLEEP_BETWEEN_PAGES = 0.05
MAX_RETRIES = 5
BACKOFF_FACTOR = 1.5

# qBittorrent
VAR_QBIT_HOST = "http://192.168.10.100:8080"
VAR_QBIT_USER = "mreclus"
VAR_QBIT_PASS = "MatMai172356!!"

OUT_JSON = Path("./radarr_qb_single.json")
# ---------------------------

# Regex pour extraire des hashes (permissif 32..64 hex, préfère 40)
HASH_RE_40 = re.compile(r"[0-9a-fA-F]{40}")
HASH_RE_32_64 = re.compile(r"[0-9a-fA-F]{32,64}")

# zone Europe/Paris (utilise zoneinfo si dispo pour DST)
USE_ZONEINFO = False
try:
    from zoneinfo import ZoneInfo  # Python 3.9+
    PARIS_TZ = ZoneInfo("Europe/Paris")
    USE_ZONEINFO = True
except Exception:
    PARIS_TZ = timezone(timedelta(hours=1))  # fallback CET (approx DST missing)

# ---------------- helpers (adaptés de ton ancien script) ----------------
def request_with_retry(url, headers, params=None, timeout=30):
    attempt = 0
    while attempt < MAX_RETRIES:
        try:
            r = requests.get(url, headers=headers, params=params, timeout=timeout)
            if r.status_code == 200:
                try:
                    return r.json()
                except ValueError:
                    raise RuntimeError("Réponse non-JSON de l'API Radarr")
            if r.status_code == 429:
                wait = (BACKOFF_FACTOR ** attempt) * 2
                time.sleep(wait)
            elif 400 <= r.status_code < 500:
                r.raise_for_status()
            else:
                wait = (BACKOFF_FACTOR ** attempt) * 1.5
                time.sleep(wait)
        except requests.RequestException:
            wait = (BACKOFF_FACTOR ** attempt) * 1.0
            time.sleep(wait)
        attempt += 1
    raise RuntimeError("Échec après plusieurs tentatives de récupération de l'API Radarr")

def fetch_all_history(base_url, api_key, page_size=200, include_movie=True):
    headers = {'X-Api-Key': api_key}
    all_items = []
    page = 1
    while True:
        params = {'page': page, 'pageSize': page_size}
        if include_movie:
            params['includeMovie'] = 'true'
        url = base_url.rstrip('/') + '/api/v3/history'
        print(f"[INFO] Fetch page {page}...", flush=True)
        data = request_with_retry(url, headers, params=params)
        if isinstance(data, list):
            page_items = data
        elif isinstance(data, dict):
            page_items = None
            for key in ('records','items','history','data','results'):
                if key in data and isinstance(data[key], list):
                    page_items = data[key]; break
            if page_items is None:
                raise RuntimeError("Réponse inattendue de l'API Radarr (dict sans liste).")
        else:
            raise RuntimeError("Réponse inattendue de l'API Radarr (format).")
        print(f"[INFO] -> reçus {len(page_items)} événements", flush=True)
        if not page_items:
            break
        all_items.extend(page_items)
        if len(page_items) < page_size:
            break
        page += 1
        time.sleep(SLEEP_BETWEEN_PAGES)
    return all_items

def group_events_by_movie(history_items):
    grouped = {}
    for ev in history_items:
        movie_info = ev.get('movie') or ev.get('Movie') or {}
        mid = None
        if isinstance(movie_info, dict):
            mid = movie_info.get('id') or movie_info.get('tmdbId') or movie_info.get('movieId')
        title = (movie_info.get('title') if isinstance(movie_info, dict) else None) or ev.get('title') or "Unknown Title"
        key = str(mid or title)
        grouped.setdefault(key, {'movie': movie_info if isinstance(movie_info, dict) else {}, 'events': []})
        grouped[key]['events'].append(ev)
    return grouped

def find_hashes_in_event(ev) -> Set[str]:
    """
    Scrute toutes les valeurs d'un event et extrait tous
    les tokens hex 32..64. Retourne ensemble de hashes normalisés.
    """
    found = set()
    # check common fields first
    cand_fields = [
        'downloadId', 'torrentInfoHash', 'torrentHash', 'id', 'guid', 'hash',
        'title', 'message', 'importedFilePath', 'importedPath'
    ]
    raw = ev.get('raw') or {}
    data = raw.get('data') if isinstance(raw.get('data'), dict) else {}
    for f in cand_fields:
        val = None
        if f in ev and ev.get(f):
            val = ev.get(f)
        if val is None and isinstance(data, dict) and f in data and data.get(f):
            val = data.get(f)
        if val is None and isinstance(raw, dict) and f in raw and raw.get(f):
            val = raw.get(f)
        if val:
            s = str(val)
            for m in HASH_RE_40.finditer(s):
                found.add(m.group(0).lower())
            for m in HASH_RE_32_64.finditer(s):
                found.add(m.group(0).lower())
    # fallback: whole-event scan
    try:
        ev_json = json.dumps(ev)
        for m in HASH_RE_40.finditer(ev_json):
            found.add(m.group(0).lower())
        for m in HASH_RE_32_64.finditer(ev_json):
            found.add(m.group(0).lower())
    except Exception:
        pass
    return found

# qB helpers
QB_LOGIN = "/api/v2/auth/login"
QB_TORRENTS_INFO = "/api/v2/torrents/info"

def qb_login(session, host, user, password):
    url = host.rstrip('/') + QB_LOGIN
    r = session.post(url, data={"username": user, "password": password}, timeout=10)
    if r.status_code != 200:
        raise RuntimeError(f"qB login failed: {r.status_code} - {r.text}")

def qb_get_torrents(session, host):
    url = host.rstrip('/') + QB_TORRENTS_INFO
    r = session.get(url, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"qB /torrents/info failed: {r.status_code} - {r.text}")
    data = r.json()
    return data if isinstance(data, list) else []

def extract_torrent_hash_from_qb_entry(t):
    for f in ("hash", "hashString", "hashes", "info_hash", "infoHash"):
        if f in t and t.get(f):
            v = t.get(f)
            if isinstance(v, (list, tuple)) and v:
                return normalize_hash(v[0])
            return normalize_hash(v)
    if 'name' in t and t.get('name'):
        h = normalize_hash(t.get('name'))
        if h:
            return h
    try:
        return normalize_hash(json.dumps(t))
    except Exception:
        return ""

def normalize_hash(h):
    if not h:
        return ""
    s = str(h).strip()
    m = HASH_RE_40.search(s)
    if m:
        return m.group(0).lower()
    m2 = HASH_RE_32_64.search(s)
    if m2:
        return m2.group(0).lower()
    return ""

def detect_indexer_from_qb_entry(t):
    possible_fields = ["trackers", "tracker", "trackerHost", "rss_feed", "rssFeedUrl", "tags", "label", "webSeed", "creator"]
    for f in possible_fields:
        v = t.get(f)
        if not v:
            continue
        if isinstance(v, (list, tuple)):
            for el in v:
                if not el:
                    continue
                s = str(el).lower()
                if "ygg" in s:
                    return "ygg"
                if "lacale" in s or "la-cale" in s:
                    return "lacale"
                m = re.search(r"(?:https?://)?([^/:]+)", s)
                if m:
                    return m.group(1).split(":")[0]
            return ",".join([str(x) for x in v if x])
        else:
            s = str(v).lower()
            if "ygg" in s:
                return "ygg"
            if "lacale" in s or "la-cale" in s:
                return "lacale"
            m = re.search(r"(?:https?://)?([^/:]+)", s)
            if m:
                return m.group(1).split(":")[0]
            return v
    name = (t.get("name") or "").lower()
    for k in ("ygg", "lacale", "yggtorrent", "gktorrent", "tpb"):
        if k in name:
            return k
    return ""

def parse_date_to_paris(v) -> str:
    if v is None:
        return ""
    try:
        if isinstance(v, (int, float)):
            dt = datetime.fromtimestamp(int(v), tz=timezone.utc)
            dt_paris = dt.astimezone(PARIS_TZ) if USE_ZONEINFO else dt.astimezone(PARIS_TZ)
            return dt_paris.isoformat()
    except Exception:
        pass
    try:
        s = str(v).strip()
        if s.endswith("Z"):
            s2 = s.replace("Z", "+00:00")
        else:
            s2 = s
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt_paris = dt.astimezone(PARIS_TZ) if USE_ZONEINFO else dt.astimezone(PARIS_TZ)
        return dt_paris.isoformat()
    except Exception:
        try:
            iv = int(float(str(v)))
            return parse_date_to_paris(iv)
        except Exception:
            return str(v)

def is_cross_category(cat: str) -> bool:
    if not cat:
        return False
    return "cross" in str(cat).lower()

# ---------------- main ----------------
def main():
    if not API_KEY or "PUT_YOUR_RADARR_API_KEY_HERE" in API_KEY:
        print("[ERROR] Configure BASE_URL et API_KEY en haut du script.", flush=True)
        return

    print("[INFO] Récupération de l'historique Radarr...", flush=True)
    history = fetch_all_history(BASE_URL, API_KEY, page_size=PAGE_SIZE, include_movie=INCLUDE_MOVIE)
    print(f"[INFO] Total événements récupérés: {len(history)}", flush=True)

    grouped = group_events_by_movie(history)
    print(f"[INFO] Total films détectés: {len(grouped)}", flush=True)

    # Build movie map
    rad_movies = {}
    for key, obj in grouped.items():
        movie = obj.get('movie') or {}
        mid = movie.get('id') or None
        title = movie.get('title') or movie.get('originalTitle') or movie.get('name') or key
        if mid:
            rad_movies[int(mid)] = {"id": int(mid), "title": title}
        else:
            rad_movies[key] = {"id": key, "title": title}

    # Extract all hashes per movie from events
    movie_hashes = {}
    movie_events_index = {}
    for key, obj in grouped.items():
        movie = obj.get('movie') or {}
        mid = movie.get('id')
        events = obj.get('events') or []
        found = set()
        for ev in events:
            found |= find_hashes_in_event(ev)
        normed = set(normalize_hash(x) for x in found if normalize_hash(x))
        map_key = int(mid) if mid else key
        movie_hashes[map_key] = normed
        movie_events_index[map_key] = events

    print("[INFO] Connexion à qBittorrent...", flush=True)
    qb_s = requests.Session()
    try:
        qb_login(qb_s, VAR_QBIT_HOST, VAR_QBIT_USER, VAR_QBIT_PASS)
    except Exception as e:
        print("[ERROR] qB login failed:", e, flush=True)
        return

    try:
        torrents = qb_get_torrents(qb_s, VAR_QBIT_HOST)
    except Exception as e:
        print("[ERROR] fetching qB torrents:", e, flush=True)
        return

    print(f"[INFO] qB returned {len(torrents)} torrents", flush=True)

    # Build hash -> info for parent torrents (all qB torrents are considered; later we will filter by movie history)
    qb_hash_info = {}
    parent_name_to_hashes = {}
    child_name_to_hashes = {}
    qb_child_info = {}

    for t in torrents:
        h = extract_torrent_hash_from_qb_entry(t)
        if not h:
            continue
        info = {"name": t.get("name"), "category": t.get("category"), "raw": t}
        # added field if any
        for cand in ("added_on", "added_on_date", "creation_date", "added", "dateAdded", "added_date", "added_on_time"):
            if cand in t and t.get(cand) is not None:
                info["added_raw"] = t.get(cand)
                break
        if "added_raw" not in info and t.get("added_on") is not None:
            info["added_raw"] = t.get("added_on")
        info["indexer"] = detect_indexer_from_qb_entry(t)
        qb_hash_info[h] = info

        # classify by name into parent/child buckets
        name = (t.get("name") or "").strip()
        cat = (t.get("category") or "").strip()
        if name:
            if is_cross_category(cat):
                child_name_to_hashes.setdefault(name, []).append(h)
                qb_child_info[h] = {"name": name, "indexer": info.get("indexer")}
            else:
                parent_name_to_hashes.setdefault(name, []).append(h)

    print(f"[INFO] Mapped {len(qb_hash_info)} qB hashes (parents & children).", flush=True)

    # Build output single JSON
    out = {"generated_at_paris": datetime.now(tz=PARIS_TZ).isoformat() if USE_ZONEINFO else datetime.now(tz=PARIS_TZ).isoformat(),
           "movies": []}

    for map_key, meta in rad_movies.items():
        mid = meta.get("id")
        title = meta.get("title")
        hashes = movie_hashes.get(map_key, set())
        torrents_list = []
        for hx in sorted(hashes):
            if not hx:
                continue
            if hx in qb_hash_info:
                qbinfo = qb_hash_info[hx]
                # find cross-seed children by exact torrent name match among child_name_to_hashes
                cross = []
                parent_name = qbinfo.get("name")
                if parent_name:
                    child_hashes = child_name_to_hashes.get(parent_name, [])
                    for ch in child_hashes:
                        child_info = qb_child_info.get(ch, {})
                        cross.append({
                            "hash": ch,
                            "qb_name": child_info.get("name"),
                            "qb_indexer": child_info.get("indexer")
                        })
                torrents_list.append({
                    "hash": hx,
                    "qb_name": qbinfo.get("name"),
                    "qb_indexer": qbinfo.get("indexer"),
                    "cross_seed": cross
                })
            else:
                # hash absent in qB -> do not include (explicitly requested)
                pass
        out["movies"].append({
            "id_radarr": mid,
            "title": title,
            "torrents": torrents_list
        })

    # Save single JSON
    OUT_JSON.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    total_present = sum(1 for m in out['movies'] for t in m['torrents'])
    print(f"[OK] Wrote {OUT_JSON} with {len(out['movies'])} movies. Total present torrents: {total_present}", flush=True)

if __name__ == "__main__":
    main()
