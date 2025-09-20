import logging
from .http import json_get
from .config import RADARR_URL, RADARR_KEY, HIST_PAGE_SIZE, HIST_MAX_MISSES, HIST_MAX_PAGES

log = logging.getLogger("webhook-cleaner")

def radarr_get(path, params=None):
    hdr = {"X-Api-Key": RADARR_KEY} if RADARR_KEY else {}
    return json_get(f"{RADARR_URL}{path}", headers=hdr, params=params or {})

def fetch_movie_history_fast(movie_id: int):
    hits, misses, page = [], 0, 1
    while True:
        payload = radarr_get("/api/v3/history", params={
            "includeMovie": "true",
            "movieIds": movie_id,
            "page": page, "pageSize": HIST_PAGE_SIZE,
            "sortKey": "date", "sortDirection": "descending"
        })
        records = payload.get("records", payload) or []
        if not records: break
        hits.extend(records); misses = 0
        total = payload.get("totalRecords")
        if total is not None and page * HIST_PAGE_SIZE >= total: break
        if page >= HIST_MAX_PAGES: break
        page += 1
    hits.sort(key=lambda x: x.get("date") or "")
    return hits

def old_hashes_for_movie(movie_id: int, current_hash: str) -> list[str]:
    cur = (current_hash or "").lower()
    seen, out = set(), []
    for it in fetch_movie_history_fast(movie_id):
        dl = (it.get("downloadId") or "").lower().strip()
        if not dl or dl == cur:
            continue
        ev = (it.get("eventType") or "").lower()
        if ev in ("download", "moviefileimported", "downloadfolderimported", "upgrade"):
            if dl not in seen:
                seen.add(dl); out.append(dl)
    return out

def media_label_from_payload(payload: dict) -> str:
    m = payload.get("movie") or {}
    title = m.get("title") or f"Movie#{m.get('id')}"
    year = m.get("year")
    return f"{title} ({year})" if year else title

def is_upgrade_event(payload: dict) -> bool:
    return str(payload.get("isUpgrade", "")).lower() in ("true","1","yes")
