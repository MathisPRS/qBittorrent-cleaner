from flask import jsonify
from ..services.radarr_services import RadarrService

def radarr_webhook(request, app):
    service = RadarrService(app)
    payload = request.get_json(silent=True)
    if payload is None:
        return jsonify({"ok": False, "error": "invalid json"}), 400

    movie = payload["movie"]
    movie_file = payload["movieFile"]
    release = payload["release"]

    title = movie["title"]
    radarr_id = str(movie["id"])
    download_id = payload["downloadId"]

    release_title = release["releaseTitle"]

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
            "path": movie_file["path"]
        }
    }

    try:
        result = service.import_completed_movie(dto)
        return jsonify({"ok": True, "result": result}), 200
    except Exception:
        app.logger.exception("radarr_controller error")
        return jsonify({"ok": False, "error": "internal error"}), 500
