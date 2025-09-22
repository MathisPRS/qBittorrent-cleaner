import logging
from datetime import datetime
from typing import Tuple, List
from .http import json_get
from .config import SONARR_URL, SONARR_KEY, HIST_PAGE_SIZE, HIST_MAX_PAGES
from .cache import get as cache_get, set as cache_set, touch_current

log = logging.getLogger("webhook-cleaner")

MAX_PAGES_SCAN = max(5, HIST_MAX_PAGES)       # profondeur de scan (descendante)
MAX_DISTINCT_HASHES = 10                      # early-stop si on a assez de doublons

def sonarr_get(path, params=None):
    hdr = {"X-Api-Key": SONARR_KEY} if SONARR_KEY else {}
    return json_get(f"{SONARR_URL}{path}", headers=hdr, params=params or {})

def _parse_date(iso: str) -> datetime:
    try:
        return datetime.fromisoformat((iso or "").replace("Z", "+00:00"))
    except Exception:
        return datetime.min

def _is_relevant_event(ev: str) -> bool:
    ev = (ev or "").lower()
    # On inclut TOUJOURS les grabs + imports/upgrades
    return ev in ("grabbed","grab","download","downloadimported","episodefileimported","upgrade","downloadfolderimported")

def _cache_key(series_id: int, episode_ids: List[int]) -> str:
    return f"sonarr:{series_id}:{','.join(str(x) for x in sorted(episode_ids))}"

def _scan_history(series_id: int, episode_ids: set[int]) -> Tuple[list[str], str | None]:
    """Scanne l'historique (tri desc). Retourne (candidats, latest). Early-stop si suffisant."""
    candidates: dict[str, datetime] = {}
    page = 1
    while page <= MAX_PAGES_SCAN:
        payload = sonarr_get("/api/v3/history", params={
            "includeEpisode": "true",
            "page": page, "pageSize": HIST_PAGE_SIZE,
            "sortKey": "date", "sortDirection": "descending"
        })
        recs = payload.get("records", payload) or []
        if not recs:
            break

        for it in recs:
            if it.get("seriesId") != series_id:
                continue
            ep = it.get("episode") or {}
            eid = ep.get("id") or it.get("episodeId")
            if eid not in episode_ids:
                continue
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

def old_hashes_via_grabs(series_id: int, episode_ids: List[int], current_hash: str) -> list[str]:
    """
    Dédup agressive: récupère (cache sinon scan) tous les hashes (grabbed + imports),
    marque le 'current_hash' comme latest si présent, et renvoie tous les autres à supprimer.
    """
    key = _cache_key(series_id, episode_ids)
    cur = (current_hash or "").lower().strip()

    entry = cache_get(key)
    if entry:
        if cur:
            touch_current(key, cur)
            entry = cache_get(key)  # relis après touch
        candidates = entry.get("candidates", []) or []
        latest = entry.get("latest")
        log.debug(f"[CACHE HIT] {key} → latest={latest}, candidates={candidates}")
    else:
        candidates, latest = _scan_history(series_id, set(episode_ids))
        if cur and cur not in candidates:
            candidates.append(cur)
            latest = cur
        cache_set(key, latest, candidates)
        log.debug(f"[CACHE MISS] {key} → latest={latest}, candidates={candidates}")

    keep = set(x for x in (latest, cur) if x)
    return [h for h in candidates if h and h not in keep]

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

# expose la clé si tu veux la passer à _purge_torrents pour prune
def cache_key(series_id: int, episode_ids: List[int]) -> str:
    return _cache_key(series_id, episode_ids)
