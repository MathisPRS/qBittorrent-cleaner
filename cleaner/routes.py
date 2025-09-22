import logging, requests
from flask import Blueprint, request, jsonify

from .config import DRY_RUN
from .qbittorrent import qb_login, qb_info_map, qb_delete
from .gotify import send_gotify
from .cache import prune_candidates

# logique Sonarr/Radarr (inclut cache_key(...) et old_hashes_via_grabs(...))
from . import sonarr as S
from . import radarr as R

bp = Blueprint("cleaner", __name__)
log = logging.getLogger("webhook-cleaner")


# ---------- Sonarr ----------
@bp.post("/sonarr")
def sonarr_hook():
    payload = request.get_json(force=True, silent=False) or {}
    event = (payload.get("eventType") or "").lower()

    # On traite imports/upgrades + grabbed pour dédup agressive
    allowed = {
        "download", "downloadimported", "downloadfolderimported",
        "episodefileimported", "upgrade", "grabbed", "grab"
    }
    if event not in allowed:
        return jsonify({"status": "ignored", "reason": f"eventType={event}"}), 200

    current_hash = (payload.get("downloadId") or "").lower().strip()

    series = payload.get("series") or {}
    series_id = series.get("id")
    episodes = payload.get("episodes") or []
    episode_ids = [e.get("id") for e in episodes if e.get("id")]

    label = S.media_label_from_payload(payload)
    upg_flag = S.is_upgrade_event(payload)

    log.info(f"[SONARR] Event={event}, isUpgrade={upg_flag}, media='{label}', current={current_hash or '<none>'}")

    if not series_id or not episode_ids:
        return jsonify({"status": "ignored", "reason": "incomplete payload"}), 200

    # clé de cache par (series_id + set d'episodes)
    cache_key = S.cache_key(series_id, episode_ids)

    # dédup agressive (grab + imports) : on garde latest/current et on propose le reste à la purge
    old_hashes = S.old_hashes_via_grabs(series_id, episode_ids, current_hash)

    return _purge_torrents(old_hashes, current_hash, label, upg_flag, cache_key=cache_key)


# ---------- Radarr ----------
@bp.post("/radarr")
def radarr_hook():
    payload = request.get_json(force=True, silent=False) or {}
    event = (payload.get("eventType") or "").lower()

    allowed = {
        "download", "upgrade", "downloadfolderimported",
        "moviefileimported", "grabbed", "grab"
    }
    if event not in allowed:
        return jsonify({"status": "ignored", "reason": f"eventType={event}"}), 200

    current_hash = (payload.get("downloadId") or "").lower().strip()
    movie = payload.get("movie") or {}
    movie_id = movie.get("id")

    label = R.media_label_from_payload(payload)
    upg_flag = R.is_upgrade_event(payload)

    log.info(f"[RADARR] Event={event}, isUpgrade={upg_flag}, media='{label}', current={current_hash or '<none>'}")

    if not movie_id:
        return jsonify({"status": "ignored", "reason": "incomplete payload"}), 200

    cache_key = R.cache_key(movie_id)
    old_hashes = R.old_hashes_via_grabs(movie_id, current_hash)

    return _purge_torrents(old_hashes, current_hash, label, upg_flag, cache_key=cache_key)


# ---------- logique commune ----------
def _purge_torrents(old_hashes: list[str], current_hash: str, label: str, upg_flag: bool, cache_key: str | None = None):
    """
    Règle métier:
      - ne JAMAIS supprimer le hash courant (current_hash)
      - supprimer tous les autres candidats encore présents dans qB
      - notifier via Gotify si au moins 1 suppression
      - mettre à jour le cache (prune) des hashes supprimés
    """
    removed, already_gone, errors = [], [], []

    # Rien à faire ?
    candidates = [h for h in old_hashes if h and h != current_hash]
    if not candidates:
        log.info("Aucun hash obsolète à traiter (liste vide ou seulement current).")
        return jsonify({"status": "ok", "media": label, "current": current_hash,
                        "removed": [], "already_gone": [], "errors": []}), 200

    with requests.Session() as s:
        qb_login(s)
        present_map = qb_info_map(s, candidates)

        if present_map:
            names_list = [present_map[h]["name"] for h in present_map]
            log.info(f"Torrents à purger (présents dans qB): {names_list}")
        else:
            log.info("Aucun torrent obsolète présent dans qBittorrent.")

        for h in candidates:
            if h not in present_map:
                already_gone.append(h)
                continue
            ok, name = qb_delete(s, h, delete_files=True, max_retry=2)
            if ok:
                removed.append({"hash": h, "name": name})
                log.info(f"✅ Supprimé: '{name}' ({h})")
            else:
                errors.append({"hash": h, "name": name})
                log.error(f"❌ Echec suppression: '{name}' ({h})")

    # Notif Gotify si suppressions
    if removed:
        names = [item.get("name") for item in removed if item.get("name")]
        lines = "\n".join(f"- {n}" for n in names[:20])
        msg = f"Dédup détectée pour {label}\n{len(removed)} torrent(s) supprimé(s):\n{lines}"
        if DRY_RUN:
            msg = "[DRY_RUN] " + msg
        send_gotify(msg)

    # Prune le cache des hashes supprimés pour rester aligné
    if cache_key and removed:
        try:
            prune_candidates(cache_key, [x["hash"] for x in removed if x.get("hash")])
        except Exception as e:
            log.debug(f"cache prune skipped ({e})")

    return jsonify({
        "status": "ok",
        "media": label,
        "current": current_hash,
        "removed": removed,
        "already_gone": already_gone,
        "errors": errors
    }), 200
