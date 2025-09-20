import logging
from .http import json_get
from .config import SONARR_URL, SONARR_KEY, HIST_PAGE_SIZE, HIST_MAX_MISSES, HIST_MAX_PAGES

log = logging.getLogger("webhook-cleaner")

def sonarr_get(path, params=None):
    hdr = {"X-Api-Key": SONARR_KEY} if SONARR_KEY else {}
    return json_get(f"{SONARR_URL}{path}", headers=hdr, params=params or {})

def fetch_episode_history_fast(series_id: int, episode_id: int):
    hits, misses, page = [], 0, 1
    while True:
        payload = sonarr_get("/api/v3/history", params={
            "includeEpisode": "true",
            "page": page, "pageSize": HIST_PAGE_SIZE,
            "sortKey": "date", "sortDirection": "descending"
        })
        records = payload.get("records", payload) or []
        if not records: break
        page_hits = []
        for it in records:
            if it.get("seriesId") != series_id: 
                continue
            ep = it.get("episode") or {}
            eid = ep.get("id") or it.get("episodeId")
            if eid == episode_id:
                page_hits.append(it)
        if page_hits: hits.extend(page_hits); misses = 0
        else: misses += 1
        total = payload.get("totalRecords")
        if misses >= HIST_MAX_MISSES: break
        if total is not None and page * HIST_PAGE_SIZE >= total: break
        if page >= HIST_MAX_PAGES: break
        page += 1
    hits.sort(key=lambda x: x.get("date") or "")
    return hits

def old_hashes_for_episodes(series_id: int, episode_ids: list[int], current_hash: str) -> list[str]:
    """Tous les anciens downloadId pour les épisodes donnés, en excluant le hash courant."""
    cur = (current_hash or "").lower()
    seen, out = set(), []
    for eid in episode_ids:
        recs = fetch_episode_history_fast(series_id, eid)
        for it in recs:
            dl = (it.get("downloadId") or "").lower().strip()
            if not dl or dl == cur: 
                continue
            ev = (it.get("eventType") or "").lower()
            if ev in ("download", "downloadimported", "episodefileimported", "upgrade", "downloadfolderimported"):
                if dl not in seen:
                    seen.add(dl); out.append(dl)
    return out

def media_label_from_payload(payload: dict) -> str:
    s = payload.get("series") or {}
    e = (payload.get("episodes") or [{}])[0]
    s_title = s.get("title") or f"Series#{s.get('id')}"
    s_num = e.get("seasonNumber"); e_num = e.get("episodeNumber")
    e_title = e.get("title") or ""
    if s_num is not None and e_num is not None:
        return f"{s_title} S{s_num:02}E{e_num:02} {e_title}".strip()
    return s_title

def is_upgrade_event(payload: dict) -> bool:
    return str(payload.get("isUpgrade", "")).lower() in ("true","1","yes")
