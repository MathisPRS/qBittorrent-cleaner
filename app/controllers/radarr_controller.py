from flask import jsonify
from app.logger import get_logger
from ..services.radarr_services import RadarrService


def radarr_webhook(request, app):
    logger = get_logger(__name__, app=app)
    service = RadarrService(app)

    payload = request.get_json(silent=True)
    if payload is None:
        logger.warning("radarr_webhook: invalid json payload")
        return jsonify({"ok": False, "error": "invalid json"}), 400

    try:
        movie = payload["movie"]
        movie_file = payload["movieFile"]
        release = payload["release"]
        title = movie["title"]
        radarr_id = str(movie["id"])
        download_id = payload["downloadId"]
        release_title = release["releaseTitle"]

    except KeyError as e:
        logger.error("radarr_webhook: missing key in payload: %s", e)
        return jsonify({"ok": False, "error": "invalid payload"}), 400

    logger.info(
        "radarr_webhook: received event for movie='%s' radarr_id=%s download_id=%s",
        title,
        radarr_id,
        download_id,
    )

    dto = {
        "radarr_id": radarr_id,
        "title": title,
        "torrent": {
            "hash": download_id,
            "title": movie_file["relativePath"],
            "releaseTitle": release_title,
            "downloadClient": payload["downloadClient"],
            "downloadClientType": payload["downloadClientType"],
            "size": movie_file["size"],
            "quality": movie_file["quality"],
            "relativePath": movie_file["relativePath"],
            "path": movie_file["path"],
        },
    }

    try:
        result = service.import_completed_movie(dto)
        return jsonify({"ok": True, "result": result}), 200
    except Exception:
        logger.exception("radarr_webhook: unexpected error during processing")
        return jsonify({"ok": False, "error": "internal error"}), 500
