# app/controllers/sonarr_controller.py
from flask import jsonify
from app.logger import get_logger
from ..services.sonarr_services import SonarrService

def sonarr_webhook(request, app):
    logger = get_logger(__name__, app=app)
    service = SonarrService(app)

    payload = request.get_json(silent=True)
    if payload is None:
        logger.warning("sonarr_webhook: invalid json payload")
        return jsonify({"ok": False, "error": "invalid json"}), 400

    # Pour ton cas métier on exige series, episodes et episodeFiles
    required = ["series", "episodes"]
    missing = [k for k in required if k not in payload or not payload.get(k)]
    if missing:
        logger.error("sonarr_webhook: missing keys in payload: %s", missing)
        return jsonify({"ok": False, "error": "missing_keys", "missing": missing}), 400

    series = payload.get("series")
    episodes = payload.get("episodes", [])
    episode_files = payload.get("episodeFiles", [])
    download_id = payload.get("downloadId")
    download_client = payload.get("downloadClient")
    download_client_type = payload.get("downloadClientType")
    release = payload.get("release") or { }
    release_type = release.get("releaseType")

    
    title = series.get("title")
    sonarr_id = series.get("id")

# Validation métier spécifique : on exige title et sonarr_id pour identifier la série
    if title is None or sonarr_id is None:
        logger.error(
            "sonarr_webhook: missing subkeys series.title/series.id; series.title=%s sonarr_id=%s",
            title, sonarr_id
        )
        return jsonify({
            "ok": False,
            "error": "missing_subkeys",
            "details": "series.title and series.id are required"
        }), 400
    
    if not episodes or not episode_files or not download_id:
        logger.info("sonarr_webhook: Missings args — ignoring event (series=%s, sonarr_id=%s)", title, sonarr_id)
        return jsonify({"ok": False, "message": "no downloadId — ignored"}), 200

    images = series.get("images", [])
    image_url = images[0].get("remoteUrl") if images and isinstance(images, list) else None

    # Build DTO minimaliste (episodes/episodeFiles complets pour clonage/matching)
    dto = {
        "sonarr_id": str(sonarr_id),
        "title": title,
        "image": image_url,
        "torrent": {
            "hash": download_id,
            "downloadClient": download_client,
            "downloadClientType": download_client_type,
            "releaseTitle": release.get("releaseTitle"),
            "releaseType": release_type,
            "sourcePath": payload.get("sourcePath"),
        },
        "episodes": episodes,
        "episodeFiles": episode_files,
    }

   
    try:
        result = service.import_completed_episodes(dto)
        return jsonify({"ok": True, "result": result}), 200
    except Exception:
        logger.exception("sonarr_webhook: unexpected error during processing")
        return jsonify({"ok": False, "error": "internal error"}), 500
