import logging
from flask import Blueprint, request, jsonify
from ..services import catalog_service, dedup_service

bp = Blueprint("cleaner", __name__)
log = logging.getLogger("webhook-cleaner")

# ---------- helpers ----------
def _label_for_sonarr(series: dict, episodes: list[dict]) -> str:
    title = series.get("title") or f"Series#{series.get('id')}"
    if not episodes:
        return title
    season = episodes[0].get("seasonNumber")
    if len(episodes) == 1:
        ep = episodes[0].get("episodeNumber")
        ep_title = episodes[0].get("title") or ""
        if season is not None and ep is not None:
            return f"{title} S{season:02}E{ep:02} {ep_title}".strip()
        return f"{title} {ep_title}".strip()
    # pack
    if season is not None:
        return f"{title} S{season:02} pack"
    return f"{title} pack"

def _label_for_radarr(movie: dict) -> str:
    t = movie.get("title")
    y = movie.get("year")
    if t and y:
        return f"{t} ({y})"
    if t:
        return t
    return f"Movie#{movie.get('id')}"

# ---------- SONARR ----------
@bp.post("/sonarr")
def sonarr_hook():
    """
    Traite uniquement les événements d'import terminé pour éviter d'impacter l'utilisateur.
    Autorisés: download, downloadimported, episodefileimported, downloadfolderimported, upgrade
    """
    payload = request.get_json(force=True, silent=False) or {}
    event = (payload.get("eventType") or "").lower()

    allowed = {
        "download", "downloadimported",
        "episodefileimported", "downloadfolderimported",
        "upgrade",
    }
    if event not in allowed:
        return jsonify({"status": "ignored", "reason": f"eventType={event}"}), 200

    current_hash = (payload.get("downloadId") or "").lower().strip()
    if not current_hash:
        return jsonify({"status": "ignored", "reason": "no downloadId in webhook"}), 200

    series = payload.get("series") or {}
    episodes = payload.get("episodes") or []
    series_id = series.get("id")
    if not series_id or not episodes:
        return jsonify({"status": "ignored", "reason": "incomplete payload"}), 200

    episode_ids = [e.get("id") for e in episodes if e.get("id")]
    if not episode_ids:
        return jsonify({"status": "ignored", "reason": "no episode ids"}), 200

    label = _label_for_sonarr(series, episodes)
    log.info(f"[SONARR] Import Completed: event={event}, media='{label}', current={current_hash}")

    # 1) MAJ du catalogue (latest/candidates/pack/timestamp)
    catalog_service.update_from_sonarr(payload)

    # 2) Dédup (calcul + purge qB + tombstones + gotify)
    removed, already_gone, errors = dedup_service.purge_for_episodes(series_id, episode_ids, label)

    return jsonify({
        "status": "ok",
        "event": event,
        "seriesId": series_id,
        "episodes": episode_ids,
        "current": current_hash,
        "removed": removed,
        "already_gone": already_gone,
        "errors": errors
    }), 200

# ---------- RADARR ----------
@bp.post("/radarr")
def radarr_hook():
    """
    Radarr: on agit aussi sur import/upgrade terminés.
    Autorisés: download, moviefileimported, downloadfolderimported, upgrade
    """
    payload = request.get_json(force=True, silent=False) or {}
    event = (payload.get("eventType") or "").lower()

    allowed = {"download", "moviefileimported", "downloadfolderimported", "upgrade"}
    if event not in allowed:
        return jsonify({"status": "ignored", "reason": f"eventType={event}"}), 200

    current_hash = (payload.get("downloadId") or "").lower().strip()
    if not current_hash:
        return jsonify({"status": "ignored", "reason": "no downloadId in webhook"}), 200

    movie = payload.get("movie") or {}
    movie_id = movie.get("id")
    if not movie_id:
        return jsonify({"status": "ignored", "reason": "incomplete payload"}), 200

    label = _label_for_radarr(movie)
    log.info(f"[RADARR] Import Completed: event={event}, media='{label}', current={current_hash}")

    # 1) MAJ du catalogue (latest/candidates/timestamp)
    catalog_service.update_from_radarr(payload)

    # 2) Dédup
    removed, already_gone, errors = dedup_service.purge_for_movie(movie_id, label)

    return jsonify({
        "status": "ok",
        "event": event,
        "movieId": movie_id,
        "current": current_hash,
        "removed": removed,
        "already_gone": already_gone,
        "errors": errors
    }), 200
