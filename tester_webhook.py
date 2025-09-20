#!/usr/bin/env python3
import configparser, os, sys, requests

CONFIG_FILE = os.getenv("CONFIG_FILE", os.path.join(os.path.dirname(__file__), "configlocal.cfg"))
cfg = configparser.ConfigParser()
if not cfg.read(CONFIG_FILE):
    print(f"[ERR] Config file not found or unreadable: {CONFIG_FILE}")
    sys.exit(1)

# ---- Config lecture ----
SONARR_URL = cfg.get("sonarr", "URL", fallback="http://localhost:8989").rstrip("/")
SONARR_KEY = cfg.get("sonarr", "API_KEY", fallback="")
RADARR_URL = cfg.get("radarr", "URL", fallback="http://localhost:7878").rstrip("/")
RADARR_KEY = cfg.get("radarr", "API_KEY", fallback="")
SERVER_PORT = int(cfg.get("server", "PORT", fallback="8124"))
REQ_TIMEOUT = int(cfg.get("general", "TEST_TIMEOUT", fallback="20"))

WEBHOOK_BASE = f"http://localhost:{SERVER_PORT}"

# ---- Helpers HTTP ----
def get_json(url, key=None, params=None):
    headers = {}
    if key:
        headers["X-Api-Key"] = key
    r = requests.get(url, headers=headers, params=params or {}, timeout=REQ_TIMEOUT)
    r.raise_for_status()
    return r.json()

# ---- SONARR ----
def sonarr_lookup_series(term: str):
    return get_json(f"{SONARR_URL}/api/v3/series/lookup", SONARR_KEY, {"term": term})

def sonarr_list_episodes(series_id: int):
    return get_json(f"{SONARR_URL}/api/v3/episode", SONARR_KEY, {"seriesId": series_id})

def latest_sonarr_hash(series_id: int, episode_id: int):
    """Retourne (downloadId le plus récent, record brut) ou (None, {})."""
    page, best = 1, None
    while page <= 20:  # scanne jusqu'à 20 pages
        payload = get_json(f"{SONARR_URL}/api/v3/history", SONARR_KEY, {
            "includeEpisode": "true",
            "page": page, "pageSize": 1000,
            "sortKey": "date", "sortDirection": "descending"
        })
        records = payload.get("records", payload) or []
        if not records:
            break
        for it in records:
            if it.get("seriesId") != series_id:
                continue
            ep = it.get("episode") or {}
            eid = ep.get("id") or it.get("episodeId")
            if eid != episode_id:
                continue
            ev = (it.get("eventType") or "").lower()
            if ev in ("download","downloadimported","episodefileimported","upgrade","downloadfolderimported"):
                dl = (it.get("downloadId") or "").lower().strip()
                if dl:
                    return dl, it
        total = payload.get("totalRecords")
        if total is not None and page * 1000 >= total:
            break
        page += 1
    return None, {}

def post_sonarr_webhook(series, episode, download_id, is_upgrade=True):
    payload = {
        "eventType": "Download",
        "isUpgrade": bool(is_upgrade),
        "downloadId": download_id,
        "series": {"id": series["id"], "title": series.get("title")},
        "episodes": [{
            "id": episode["id"],
            "seasonNumber": episode.get("seasonNumber"),
            "episodeNumber": episode.get("episodeNumber"),
            "title": episode.get("title") or f"S{episode.get('seasonNumber')}E{episode.get('episodeNumber')}"
        }]
    }
    r = requests.post(f"{WEBHOOK_BASE}/sonarr", json=payload, timeout=REQ_TIMEOUT)
    print("[POST /sonarr]", r.status_code, r.text[:400])

# ---- RADARR ----
def radarr_lookup_movie(term: str):
    return get_json(f"{RADARR_URL}/api/v3/movie/lookup", RADARR_KEY, {"term": term})

def latest_radarr_hash(movie_id: int):
    page, best = 1, None
    while page <= 20:
        payload = get_json(f"{RADARR_URL}/api/v3/history", RADARR_KEY, {
            "includeMovie": "true",
            "movieIds": movie_id,
            "page": page, "pageSize": 1000,
            "sortKey": "date", "sortDirection": "descending"
        })
        records = payload.get("records", payload) or []
        if not records: break
        for it in records:
            ev = (it.get("eventType") or "").lower()
            if ev in ("download","moviefileimported","downloadfolderimported","upgrade"):
                dl = (it.get("downloadId") or "").lower().strip()
                if dl:
                    return dl, it
        total = payload.get("totalRecords")
        if total is not None and page * 1000 >= total: break
        page += 1
    return None, {}

def post_radarr_webhook(movie, download_id, is_upgrade=True):
    payload = {
        "eventType": "Download",
        "isUpgrade": bool(is_upgrade),
        "downloadId": download_id,
        "movie": {"id": movie["id"], "title": movie.get("title"), "year": movie.get("year")}
    }
    r = requests.post(f"{WEBHOOK_BASE}/radarr", json=payload, timeout=REQ_TIMEOUT)
    print("[POST /radarr]", r.status_code, r.text[:400])

# ---- MAIN ----
def main():
    print("Test webhook cleaner")
    mode = input("Type? (serie/film) [serie]: ").strip().lower() or "serie"

    if mode == "serie":
        title = input("Nom de la série: ").strip()
        season = int(input("Numéro de saison: ").strip())
        episode_num = int(input("Numéro d'épisode: ").strip())

        print(f"[i] Lookup série '{title}'…")
        arr = sonarr_lookup_series(title)
        if not arr:
            print("[ERR] Série introuvable"); sys.exit(3)
        s = arr[0]; sid = s["id"]

        eps = sonarr_list_episodes(sid)
        ep = next((e for e in eps if e.get("seasonNumber")==season and e.get("episodeNumber")==episode_num), None)
        if not ep:
            print("[ERR] Épisode S%02dE%02d introuvable" % (season, episode_num)); sys.exit(4)

        print(f"[OK] Série: {s.get('title')} id={sid} | Episode: {ep.get('title')} id={ep.get('id')}")
        dlid, _ = latest_sonarr_hash(sid, ep["id"])
        if not dlid:
            print("[WARN] Aucun downloadId trouvé → simulation.")
            dlid = "deadbeef"*5
        else:
            print(f"[OK] Dernier downloadId: {dlid}")

        if input("Envoyer le webhook vers /sonarr ? (o/N): ").lower()=="o":
            post_sonarr_webhook({"id": sid, "title": s.get("title")}, ep, dlid)

    else:  # film
        title = input("Titre du film: ").strip()
        year = input("Année (optionnel): ").strip()
        term = title if not year else f"{title} ({year})"

        print(f"[i] Lookup film '{term}'…")
        arr = radarr_lookup_movie(term)
        if not arr:
            print("[ERR] Film introuvable"); sys.exit(5)
        m = arr[0]; mid = m["id"]

        print(f"[OK] Film: {m.get('title')} ({m.get('year')}) id={mid}")
        dlid, _ = latest_radarr_hash(mid)
        if not dlid:
            print("[WARN] Aucun downloadId trouvé → simulation.")
            dlid = "cafebabe"*5
        else:
            print(f"[OK] Dernier downloadId: {dlid}")

        if input("Envoyer le webhook vers /radarr ? (o/N): ").lower()=="o":
            post_radarr_webhook(m, dlid)

if __name__ == "__main__":
    try:
        main()
    except requests.HTTPError as e:
        print("[HTTP ERROR]", e, getattr(e.response, "text", "")[:500]); sys.exit(10)
    except Exception as e:
        print("[ERROR]", e); sys.exit(11)
