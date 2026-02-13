# app/controllers/radarr_controller.py
from flask import jsonify
from ..services.radarr_services import RadarrService

def radarr_webhook(request, app):
    service = RadarrService(app)
    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({"ok": False, "error": "invalid json"}), 400

    movie = payload.get("movie") or {}
    movie_file = payload.get("movieFile") or {}
    # downloadId often contains the download client's id (qB torrent hash)
    download_id = payload.get("downloadId") or movie_file.get("downloadId")

    title = movie.get("title") or (payload.get("remoteMovie") or {}).get("title")
    radarr_id = movie.get("id")
    # minimal validation
    if not title:
        return jsonify({"ok": False, "error": "missing title"}), 400

    # build DTO (normalize what we need)
    dto = {
        "radarr_id": str(radarr_id) if radarr_id is not None else None,
        "title": title,
        "torrent": {
            # treat downloadId as the torrent identifier / hash
            "hash": download_id,
            "downloadClient": payload.get("downloadClient"),
            "downloadClientType": payload.get("downloadClientType"),
            "size": movie_file.get("size") or (payload.get("release") or {}).get("size"),
            "quality": movie_file.get("quality") or (payload.get("release") or {}).get("quality"),
            "relativePath": movie_file.get("relativePath"),
            "path": movie_file.get("path") or movie.get("folderPath") or movie_file.get("sourcePath")
        },
        "raw": payload
    }

    
    try:
        result = service.import_completed_movie(dto)
        return jsonify({"ok": True, "result": result}), 200
    except Exception as e:
        # controller should not raise internal tracebacks to client
        app.logger.exception("radarr_controller error")
        return jsonify({"ok": False, "error": "internal error"}), 500
