#!/usr/bin/env python3
import os, sys, argparse, time, logging
from collections import defaultdict
from datetime import datetime

# Permet d'importer cleaner.* depuis la racine
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
sys.path.insert(0, ROOT_DIR)

import requests

from cleaner.config import (
    SONARR_URL, SONARR_KEY, RADARR_URL, RADARR_KEY,
    QBIT_HOST, QBIT_USER, QBIT_PASS,
    HIST_PAGE_SIZE, HIST_MAX_PAGES
)
from cleaner.cache import get as cache_get, put as cache_put
from cleaner.http import json_get

log = logging.getLogger("catalog-builder")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

# ------------ util ------------
def parse_dt(iso: str) -> datetime:
    try:
        return datetime.fromisoformat((iso or "").replace("Z", "+00:00"))
    except Exception:
        return datetime.min

def qb_login(sess: requests.Session):
    r = sess.post(f"{QBIT_HOST}/api/v2/auth/login",
                  data={"username": QBIT_USER, "password": QBIT_PASS}, timeout=15)
    if r.text.strip() != "Ok.":
        raise RuntimeError(f"qBittorrent login failed: {r.text}")

def qb_all_torrents(sess: requests.Session) -> list[dict]:
    r = sess.get(f"{QBIT_HOST}/api/v2/torrents/info", timeout=30)
    r.raise_for_status()
    return r.json()

def sonarr_history_iter(max_pages: int):
    page = 1
    while page <= max_pages:
        payload = json_get(f"{SONARR_URL}/api/v3/history",
                           headers={"X-Api-Key": SONARR_KEY},
                           params={
                               "includeEpisode": "true",
                               "page": page, "pageSize": HIST_PAGE_SIZE,
                               "sortKey": "date", "sortDirection": "descending"
                           })
        records = payload.get("records", payload) or []
        if not records:
            break
        for it in records:
            yield it
        total = payload.get("totalRecords")
        if total is not None and page * HIST_PAGE_SIZE >= total:
            break
        page += 1

def radarr_history_iter(max_pages: int):
    page = 1
    while page <= max_pages:
        payload = json_get(f"{RADARR_URL}/api/v3/history",
                           headers={"X-Api-Key": RADARR_KEY},
                           params={
                               "includeMovie": "true",
                               "page": page, "pageSize": HIST_PAGE_SIZE,
                               "sortKey": "date", "sortDirection": "descending"
                           })
        records = payload.get("records", payload) or []
        if not records:
            break
        for it in records:
            yield it
        total = payload.get("totalRecords")
        if total is not None and page * HIST_PAGE_SIZE >= total:
            break
        page += 1

def is_relevant_sonarr(ev: str) -> bool:
    ev = (ev or "").lower()
    return ev in ("grabbed","grab","download","downloadimported","episodefileimported","upgrade","downloadfolderimported")

def is_relevant_radarr(ev: str) -> bool:
    ev = (ev or "").lower()
    return ev in ("grabbed","grab","download","moviefileimported","downloadfolderimported","upgrade")

def sonarr_key(series_id: int, episode_ids: list[int]) -> str:
    return f"sonarr:{series_id}:{','.join(str(x) for x in sorted(episode_ids))}"

def radarr_key(movie_id: int) -> str:
    return f"radarr:{movie_id}"

# ------------ build ------------
def build_catalog(pages_sonarr: int, pages_radarr: int, qb_only: bool):
    """
    - Récupère la liste de tous les torrents qB (hashes)
    - Scanne Sonarr & Radarr (DESC) et construit un catalogue latest/candidates par clé
    - Écrit dans le cache cleaner
    """
    # 1) QBIT → set de hashes + dates (si besoin)
    with requests.Session() as sess:
        log.info("Connexion qBittorrent…")
        qb_login(sess)
        qbt = qb_all_torrents(sess)
    qb_hashes = { (t.get("hash") or "").lower(): t for t in qbt }
    log.info(f"qB: {len(qb_hashes)} torrents chargés.")

    # Structures temporaires (par clé)
    sonarr_map: dict[str, dict[str, datetime]] = defaultdict(dict)  # key -> {hash -> last_seen_date}
    radarr_map: dict[str, dict[str, datetime]] = defaultdict(dict)

    # 2) SONARR
    if SONARR_KEY and SONARR_URL:
        log.info(f"Scan Sonarr history (pages={pages_sonarr})…")
        count = 0
        for it in sonarr_history_iter(max_pages=pages_sonarr):
            ev = (it.get("eventType") or "").lower()
            if not is_relevant_sonarr(ev):
                continue
            dl = (it.get("downloadId") or "").lower().strip()
            if not dl:
                continue
            if qb_only and dl not in qb_hashes:
                continue  # on ne garde que ce qui existe en qB si demandé

            series_id = it.get("seriesId")
            ep = it.get("episode") or {}
            eid = ep.get("id") or it.get("episodeId")
            if not series_id or not eid:
                continue
            key = sonarr_key(series_id, [eid])
            dt = parse_dt(it.get("date"))
            prev = sonarr_map[key].get(dl)
            if (prev is None) or (dt > prev):
                sonarr_map[key][dl] = dt
            count += 1
        log.info(f"Sonarr: {len(sonarr_map)} clés peuplées ({count} événements gardés).")
    else:
        log.info("Sonarr désactivé (URL/API KEY manquants).")

    # 3) RADARR
    if RADARR_KEY and RADARR_URL:
        log.info(f"Scan Radarr history (pages={pages_radarr})…")
        count = 0
        for it in radarr_history_iter(max_pages=pages_radarr):
            ev = (it.get("eventType") or "").lower()
            if not is_relevant_radarr(ev):
                continue
            dl = (it.get("downloadId") or "").lower().strip()
            if not dl:
                continue
            if qb_only and dl not in qb_hashes:
                continue
            # movie id
            movie = it.get("movie") or {}
            mid = movie.get("id") or it.get("movieId")
            if not mid:
                continue
            key = radarr_key(mid)
            dt = parse_dt(it.get("date"))
            prev = radarr_map[key].get(dl)
            if (prev is None) or (dt > prev):
                radarr_map[key][dl] = dt
            count += 1
        log.info(f"Radarr: {len(radarr_map)} clés peuplées ({count} événements gardés).")
    else:
        log.info("Radarr désactivé (URL/API KEY manquants).")

    # 4) Ecriture dans le cache (latest + candidates)
    total_keys = 0
    for key, hmap in sonarr_map.items():
        if not hmap:
            continue
        latest = max(hmap.items(), key=lambda kv: kv[1])[0]
        candidates = list(hmap.keys())
        cache_put(key, latest, candidates)
        total_keys += 1
    for key, hmap in radarr_map.items():
        if not hmap:
            continue
        latest = max(hmap.items(), key=lambda kv: kv[1])[0]
        candidates = list(hmap.keys())
        cache_put(key, latest, candidates)
        total_keys += 1

    log.info(f"Catalogue écrit dans le cache: {total_keys} clés (sonarr+radarr).")
    log.info("Terminé ✅")


def main():
    ap = argparse.ArgumentParser(description="Pré-remplit le cache cleaner (catalogue) en scannant qB + Sonarr/Radarr.")
    ap.add_argument("--pages-sonarr", type=int, default=max(10, HIST_MAX_PAGES),
                    help="Nombre de pages Sonarr à scanner (tri DESC). Par défaut max(10, HIST_MAX_PAGES).")
    ap.add_argument("--pages-radarr", type=int, default=max(10, HIST_MAX_PAGES),
                    help="Nombre de pages Radarr à scanner (tri DESC). Par défaut max(10, HIST_MAX_PAGES).")
    ap.add_argument("--qb-only", action="store_true",
                    help="Ne catalogue que les hashes actuellement présents dans qBittorrent.")
    args = ap.parse_args()

    build_catalog(args.pages_sonarr, args.pages_radarr, args.qb_only)

if __name__ == "__main__":
    main()
