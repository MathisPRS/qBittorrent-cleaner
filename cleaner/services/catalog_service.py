from datetime import datetime, timezone
from ..repositories import catalog_repo
from ..domain.models import ensure_episode, ensure_movie
from ..domain.rules import promote_latest

def _now_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def update_from_sonarr(payload: dict):
    cat = catalog_repo.load_catalog()
    series = payload.get("series") or {}
    series_id = series.get("id")
    episodes = payload.get("episodes") or []
    current_hash = (payload.get("downloadId") or "").lower().strip()
    season = episodes[0].get("seasonNumber") if episodes else None

    s = cat["sonarr"].setdefault(str(series_id), {"seriesTitle": series.get("title"), "episodes": {}, "packs": {}})
    if len(episodes) > 1:
        s["packs"].setdefault(current_hash, [])
        for e in episodes:
            eid = str(e.get("id"))
            if eid not in s["packs"][current_hash]:
                s["packs"][current_hash].append(eid)

    for e in episodes:
        eid = e.get("id")
        ep = ensure_episode(cat, series_id, series.get("title"), eid,
                            e.get("seasonNumber"), e.get("episodeNumber"), e.get("title"))
        promote_latest(ep, current_hash)
        ep["max_event_at"] = _now_iso()

    catalog_repo.save_catalog(cat)

def update_from_radarr(payload: dict):
    cat = catalog_repo.load_catalog()
    movie = payload.get("movie") or {}
    movie_id = movie.get("id")
    current_hash = (payload.get("downloadId") or "").lower().strip()

    m = ensure_movie(cat, movie_id, movie.get("title"), movie.get("year"))
    promote_latest(m, current_hash)
    m["max_event_at"] = _now_iso()

    catalog_repo.save_catalog(cat)
