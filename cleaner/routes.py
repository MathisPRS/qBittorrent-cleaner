import logging, requests
from flask import Blueprint, request, jsonify
from .config import ONLY_UPGRADES, DRY_RUN
from .qbittorrent import qb_login, qb_info_map, qb_delete
from .gotify import send_gotify
from . import sonarr as S
from . import radarr as R

bp = Blueprint("cleaner", __name__)
log = logging.getLogger("webhook-cleaner")

# ---------- Sonarr ----------
@bp.post("/sonarr")
def sonarr_hook():
    payload = request.get_json(force=True, silent=False) or {}
    event = (payload.get("eventType") or "").lower()

    # on traite les imports / upgrades Sonarr (y compris pack → épisodes multiples)
    if event not in ("download", "downloadimported", "downloadfolderimported", "episodefileimported", "upgrade"):
        return jsonify({"status": "ignored", "reason": f"eventType={event}"}), 200

    current_hash = (payload.get("downloadId") or "").lower()
    if not current_hash:
        return jsonify({"status": "ignored", "reason": "no downloadId in webhook"}), 200

    series = payload.get("series") or {}
    series_id = series.get("id")
    episodes = payload.get("episodes") or []
    episode_ids = [e.get("id") for e in episodes if e.get("id")]

    label = S.media_label_from_payload(payload)
    upg_flag = S.is_upgrade_event(payload)

    log.info(f"[SONARR] Import Completed: event={event}, isUpgrade={upg_flag}, media='{label}', current={current_hash}")

    if not series_id or not episode_ids:
        log.warning("payload incomplete (series_id/episode_ids manquants) → ignore.")
        return jsonify({"status": "ignored", "reason": "incomplete payload"}), 200

    # prend en compte le cas pack (episodes multiples dans le payload) et remonte tous les anciens hashes liés
    old_hashes = S.old_hashes_for_episodes(series_id, episode_ids, current_hash)
    return _purge_torrents(old_hashes, current_hash, label, upg_flag)

# ---------- Radarr ----------
@bp.post("/radarr")
def radarr_hook():
    payload = request.get_json(force=True, silent=False) or {}

    event = (payload.get("eventType") or "").lower()
    # Radarr n'a que Download (+ isUpgrade); on tolère quelques variantes si présentes
    if event not in ("download", "upgrade", "downloadfolderimported", "moviefileimported"):
        return jsonify({"status": "ignored", "reason": f"eventType={event}"}), 200

    current_hash = (payload.get("downloadId") or "").lower()
    if not current_hash:
        return jsonify({"status": "ignored", "reason": "no downloadId in webhook"}), 200

    movie = payload.get("movie") or {}
    movie_id = movie.get("id")

    label = R.media_label_from_payload(payload)
    upg_flag = R.is_upgrade_event(payload)

    log.info(f"[RADARR] Import (Download): isUpgrade={upg_flag}, media='{label}', current={current_hash}")

    if not movie_id:
        log.warning("payload incomplete (movie_id manquant) → ignore.")
        return jsonify({"status": "ignored", "reason": "incomplete payload"}), 200

    old_hashes = R.old_hashes_for_movie(movie_id, current_hash)
    return _purge_torrents(old_hashes, current_hash, label, upg_flag)

# ---------- logique commune ----------
def _purge_torrents(old_hashes: list[str], current_hash: str, label: str, upg_flag: bool):
    # Règle métier: on ne supprime JAMAIS le hash courant; on supprime "les anciens" s'ils existent,
    # et si ONLY_UPGRADES=True, on exige isUpgrade ou au moins un ancien hash identifié.
    if ONLY_UPGRADES and not upg_flag and len(old_hashes) == 0:
        log.info("Pas d’anciens hashes et pas de flag upgrade → ignore (ONLY_UPGRADES).")
        return jsonify({"status": "ignored", "reason": "not upgrade"}), 200

    removed, already_gone, errors = [], [], []
    with requests.Session() as s:
        qb_login(s)
        present_map = qb_info_map(s, [h for h in old_hashes if h != current_hash])

        if present_map:
            names_list = [present_map[h]["name"] for h in present_map]
            log.info(f"Torrents à purger (présents dans qB): {names_list}")
        else:
            log.info("Aucun torrent obsolète présent dans qBittorrent.")

        for h in old_hashes:
            if h == current_hash:
                continue  # ne JAMAIS supprimer le hash courant
            if h not in present_map:
                already_gone.append(h); continue
            ok, name = qb_delete(s, h, delete_files=True, max_retry=2)
            if ok:
                removed.append({"hash": h, "name": name})
                log.info(f"✅ Supprimé: '{name}' ({h})")
            else:
                errors.append({"hash": h, "name": name})
                log.error(f"❌ Echec suppression: '{name}' ({h})")

    if removed:
        names = [item.get("name") for item in removed if item.get("name")]
        lines = "\n".join(f"- {n}" for n in names[:20])
        msg = (f"Upgrade détecté pour {label}\n{len(removed)} torrent(s) supprimé(s):\n{lines}")
        if DRY_RUN: msg = "[DRY_RUN] " + msg
        send_gotify(msg)

    return jsonify({
        "status": "ok",
        "media": label,
        "current": current_hash,
        "removed": removed,
        "already_gone": already_gone,
        "errors": errors
    }), 200
