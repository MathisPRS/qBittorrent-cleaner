# app/controllers/sonarr_controller.py
from flask import jsonify
from app.logger import get_logger
from ..services.sonarr_services import SonarrService

def sonarr_webhook(request, app):
    logger = get_logger(__name__, app=app)
    service = SonarrService(app)

    payload = request.get_json(silent=True)
    if not payload:
        logger.warning("sonarr_webhook: invalid or empty json payload")
        return jsonify({"ok": False, "error": "invalid json"}), 400

    # required keys
    required = ("series", "episodes")
    missing = [k for k in required if not payload.get(k)]
    if missing:
        logger.error("sonarr_webhook: missing keys in payload: %s", missing)
        return jsonify({"ok": False, "error": "missing_keys", "missing": missing}), 400

    series = payload["series"]
    episodes = payload["episodes"]
    episode_files = payload.get("episodeFiles")
    download_id = payload.get("downloadId")

    title = series.get("title")
    sonarr_id = series.get("id")

    if not title or sonarr_id is None:
        logger.error(
            "sonarr_webhook: missing series.title or series.id (title=%s id=%s)",
            title, sonarr_id
        )
        return jsonify({
            "ok": False,
            "error": "missing_subkeys",
            "details": "series.title and series.id are required"
        }), 400

    # Ignore non-actionable events
    if not episodes or not episode_files or not download_id:
        logger.info(
            "sonarr_webhook: missing actionable data — ignoring event (series=%s sonarr_id=%s)",
            title, sonarr_id
        )
        return jsonify({"ok": False, "message": "ignored"}), 200

    images = series.get("images") or []
    image_url = images[0].get("remoteUrl") if images else None

    dto = {
        "sonarr_id": str(sonarr_id),
        "title": title,
        "image": image_url,
        "torrent": {
            "hash": download_id,
            "downloadClient": payload.get("downloadClient"),
            "downloadClientType": payload.get("downloadClientType"),
            "releaseTitle": (payload.get("release") or {}).get("releaseTitle"),
            "releaseType": (payload.get("release") or {}).get("releaseType"),
            "sourcePath": payload.get("sourcePath"),
        },
        "episodes": episodes,
        "episodeFiles": episode_files,
    }
    try:
        result = service.import_completed_episodes(dto)

        if not isinstance(result, dict):
            logger.error("sonarr_webhook: service returned unexpected type: %s", type(result))
            return jsonify({"ok": False, "error": "invalid_service_response"}), 500

        action = result.get("action")

        action_map = {
            "create_series_and_episodes": (201, "info", f"Série créée avec ses épisodes : {title}"),
            "sync_completed_no_deletes": (200,"info", f"Série synchronisée (aucune suppression) : {title}"),
            "replace_and_cleanup": (200,"info",f"Série mise à jour avec remplacement et nettoyage : {title}"),
            "created": (201, "info", f"Épisode créé pour la série : {title}"),
            "updated": (200, "info", f"Épisode mis à jour pour la série : {title}"),
            "same": (200, "info", f"Aucune modification nécessaire : {title}"),
            "error": ( 422, "error", f"Erreur métier lors du traitement de la série : {title}"),
        }

        status, level, message = action_map.get(action,(200,"info",f"Import terminé (action={action}) : {title}"))
        _log_block(logger, level, message)
        return jsonify({"ok": action != "error", "result": result}), status

    except Exception:
        logger.exception("sonarr_webhook: unexpected error during processing")
        return jsonify({"ok": False, "error": "internal error"}), 500
    

def _log_block(logger, level: str, message: str):
    LOG_SEPARATOR = "-" * 51
    log_fn = getattr(logger, level)
    log_fn("\n%s\n%s\n%s", LOG_SEPARATOR, message, LOG_SEPARATOR)
