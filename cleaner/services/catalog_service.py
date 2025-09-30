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

    if not series_id or not episodes or not current_hash:
        return  # payload incomplet: on ignore silencieusement

    # --- ensure structure for this series (migration-friendly) ---
    s = cat["sonarr"].setdefault(str(series_id), {})
    # migrer métadonnées si besoin
    if "seriesTitle" not in s and series.get("title"):
        s["seriesTitle"] = series.get("title")
    # garantir sous-structures
    if "episodes" not in s or not isinstance(s["episodes"], dict):
        s["episodes"] = {}
    if "packs" not in s or not isinstance(s["packs"], dict):
        s["packs"] = {}

    # --- si pack (plusieurs épisodes), enregistrer le mapping pack -> episodeIds ---
    if len(episodes) > 1:
        lst = s["packs"].setdefault(current_hash, [])
        for e in episodes:
            eid = str(e.get("id"))
            if eid and eid not in lst:
                lst.append(eid)

    # --- promote latest pour chaque épisode du payload ---
    now_iso = _now_iso()
    for e in episodes:
        eid = e.get("id")
        if not eid:
            continue
        ep = ensure_episode(cat, series_id, series.get("title"), eid,
                            e.get("seasonNumber"), e.get("episodeNumber"), e.get("title"))
        promote_latest(ep, current_hash)
        ep["max_event_at"] = now_iso

    catalog_repo.save_catalog(cat)

def update_from_radarr(payload: dict):
    cat = catalog_repo.load_catalog()
    movie = payload.get("movie") or {}
    movie_id = movie.get("id")
    current_hash = (payload.get("downloadId") or "").lower().strip()
    if not movie_id or not current_hash:
        return

    m = ensure_movie(cat, movie_id, movie.get("title"), movie.get("year"))
    promote_latest(m, current_hash)
    m["max_event_at"] = _now_iso()

    catalog_repo.save_catalog(cat)
