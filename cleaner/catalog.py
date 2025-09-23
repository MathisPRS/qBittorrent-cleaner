import os, json, logging
from datetime import datetime, timezone
from typing import Iterable

from .config import CATALOG_FILE

log = logging.getLogger("webhook-cleaner")

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def _ensure_dir():
    d = os.path.dirname(CATALOG_FILE)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)

def load_catalog() -> dict:
    try:
        with open(CATALOG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"sonarr": {}, "radarr": {}, "meta": {}}

def save_catalog(cat: dict):
    try:
        _ensure_dir()
        tmp = CATALOG_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cat, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CATALOG_FILE)
    except Exception as e:
        log.warning(f"catalog save failed: {e}")

# ---------- mise à jour depuis webhook ----------
def _ensure_episode(cat: dict, series_id: int, series_title: str | None,
                    episode_id: int, season: int | None, epnum: int | None, ep_title: str | None) -> dict:
    s = cat["sonarr"].setdefault(str(series_id), {"seriesTitle": series_title, "episodes": {}, "packs": {}})
    e = s["episodes"].setdefault(str(episode_id), {
        "season": season, "episode": epnum, "title": ep_title,
        "latest": None, "candidates": [], "removed": [], "max_event_at": _now_iso()
    })
    # complète les champs si absents
    if season is not None and e.get("season") is None: e["season"] = season
    if epnum  is not None and e.get("episode") is None: e["episode"] = epnum
    if ep_title and not e.get("title"): e["title"] = ep_title
    return e

def _ensure_movie(cat: dict, movie_id: int, title: str | None, year: int | None) -> dict:
    m = cat["radarr"].setdefault(str(movie_id), {
        "title": title, "year": year, "latest": None, "candidates": [], "removed": [], "max_event_at": _now_iso()
    })
    if title and not m.get("title"): m["title"] = title
    if year and not m.get("year"):   m["year"] = year
    return m

def _append_if_missing(lst: list[str], value: str):
    if value and value not in lst:
        lst.append(value)

def update_sonarr_latest(cat: dict, series_id: int, series_title: str | None,
                         episode_ids: list[int], season: int | None, epnums: list[int | None],
                         ep_titles: list[str | None], current_hash: str):
    """
    - met à jour latest pour chaque épisode concerné
    - ajoute current en candidates s'il n'y est pas
    - enregistre un "pack" si plusieurs épisodes arrivent avec le même hash
    """
    current_hash = (current_hash or "").lower().strip()
    s = cat["sonarr"].setdefault(str(series_id), {"seriesTitle": series_title, "episodes": {}, "packs": {}})

    # pack awareness : on associe ce hash à la liste des épisodes
    if len(episode_ids) > 1:
        pack_eps = sorted(str(eid) for eid in episode_ids)
        s["packs"].setdefault(current_hash, [])
        for eid in pack_eps:
            if eid not in s["packs"][current_hash]:
                s["packs"][current_hash].append(eid)

    for idx, eid in enumerate(episode_ids):
        ep = _ensure_episode(
            cat, series_id, series_title,
            eid, season, epnums[idx] if idx < len(epnums) else None,
            ep_titles[idx] if idx < len(ep_titles) else None
        )
        # promote current to latest
        if ep.get("latest") != current_hash:
            old_latest = ep.get("latest")
            if old_latest:
                _append_if_missing(ep["candidates"], old_latest)
            ep["latest"] = current_hash
        # ensure current is in candidates too (utile si latest change plus tard)
        _append_if_missing(ep["candidates"], current_hash)
        # refresh timestamp
        ep["max_event_at"] = _now_iso()

def update_radarr_latest(cat: dict, movie_id: int, title: str | None, year: int | None, current_hash: str):
    current_hash = (current_hash or "").lower().strip()
    m = _ensure_movie(cat, movie_id, title, year)
    if m.get("latest") != current_hash:
        old_latest = m.get("latest")
        if old_latest:
            _append_if_missing(m["candidates"], old_latest)
        m["latest"] = current_hash
    _append_if_missing(m["candidates"], current_hash)
    m["max_event_at"] = _now_iso()

def compute_to_delete_ep(entry: dict) -> list[str]:
    latest = (entry.get("latest") or "").lower().strip()
    removed = set((entry.get("removed") or []))
    out = []
    for h in entry.get("candidates", []):
        h = (h or "").lower().strip()
        if h and h != latest and h not in removed:
            out.append(h)
    return list(dict.fromkeys(out))  # keep order

def mark_removed_ep(entry: dict, removed_hashes: Iterable[str]):
    rs = set(entry.get("removed") or [])
    for h in removed_hashes:
        if h:
            rs.add(h.lower().strip())
    entry["removed"] = list(sorted(rs))

def compute_to_delete_movie(entry: dict) -> list[str]:
    latest = (entry.get("latest") or "").lower().strip()
    removed = set((entry.get("removed") or []))
    out = []
    for h in entry.get("candidates", []):
        h = (h or "").lower().strip()
        if h and h != latest and h not in removed:
            out.append(h)
    return list(dict.fromkeys(out))

def mark_removed_movie(entry: dict, removed_hashes: Iterable[str]):
    rs = set(entry.get("removed") or [])
    for h in removed_hashes:
        if h:
            rs.add(h.lower().strip())
    entry["removed"] = list(sorted(rs))
