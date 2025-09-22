import logging
from datetime import datetime
from typing import Tuple
from .http import json_get
from .config import RADARR_URL, RADARR_KEY, HIST_PAGE_SIZE, HIST_MAX_PAGES
from .cache import get as cache_get, put as cache_put, touch_current

log = logging.getLogger("webhook-cleaner")

MAX_PAGES_SCAN = max(5, HIST_MAX_PAGES)
MAX_DISTINCT_HASHES = 10

def radarr_get(path, params=None):
    hdr = {"X-Api-Key": RADARR_KEY} if RADARR_KEY else {}
    return json_get(f"{RADARR_URL}{path}", headers=hdr, params=params or {})

def _parse_date(iso: str) -> datetime:
    try:
        return datetime.fromisoformat((iso or "").replace("Z", "+00:00"))
    except Exception:
        return datetime.min

def _is_relevant_event(ev: str) -> bool:
    ev = (ev or "").lower()
    return ev in ("grabbed","grab","download","moviefileimported","downloadfolderimported","upgrade")

def _cache_key(movie_id: int) -> str:
    return f"radarr:{movie_id}"

def _scan_history(movie_id: int) -> Tuple[list[str], str | None]:
    candidates: dict[str, datetime] = {}
    page = 1
    while page <= MAX_PAGES_SCAN:
        payload = radarr_get("/api/v3/history", params={
            "includeMovie": "true",
            "movieIds": movie_id,
            "page": page, "pageSize": HIST_PAGE_SIZE,
            "sortKey": "date", "sortDirection": "descending"
        })
        recs = payload.get("records", payload) or []
        if not recs:
            break
        for it in recs:
            if not _is_relevant_event(it.get("eventType")):
                continue
            dl = (it.get("downloadId") or "").lower().strip()
            if not dl:
                continue
            dt = _parse_date(it.get("date"))
            if (dl not in candidates) or (dt > candidates[dl]):
                candidates[dl] = dt
        if len(candidates) >= MAX_DISTINCT_HASHES:
            break
        total = payload.get("totalRecords")
        if total is not None and page * HIST_PAGE_SIZE >= total:
            break
        page += 1

    if not candidates:
        return [], None
    latest = max(candidates.items(), key=lambda kv: kv[1])[0]
    return list(candidates.keys()), latest

def old_hashes_via_grabs(movie_id: int, current_hash: str) -> list[str]:
    key = _cache_key(movie_id)
    cur = (current_hash or "").lower().strip()

    entry = cache_get(key)
    if entry:
        if cur:
            touch_current(key, cur)
            entry = cache_get(key)
        candidates = entry.get("candidates", []) or []
        latest = entry.get("latest")
        log.debug(f"[CACHE HIT] {key} → latest={latest}, candidates={candidates}")
    else:
        candidates, latest = _scan_history(movie_id)
        if cur and cur not in candidates:
            candidates.append(cur)
            latest = cur
        cache_put(key, latest, candidates)   # <-- put()
        log.debug(f"[CACHE MISS] {key} → latest={latest}, candidates={candidates}")

    keep = set(x for x in (latest, cur) if x)
    return [h for h in candidates if h and h not in keep]

def media_label_from_payload(payload: dict) -> str:
    m = payload.get("movie") or {}
    title = m.get("title") or f"Movie#{m.get('id')}"
    year = m.get("year")
    return f"{title} ({year})" if year else title

def is_upgrade_event(payload: dict) -> bool:
    return str(payload.get("isUpgrade", "")).lower() in ("true","1","yes")

def cache_key(movie_id: int) -> str:
    return _cache_key(movie_id)
