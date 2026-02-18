# app/controllers/radarr_controller.py
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

    # movie and release are required for any processing; downloadId may be absent for some Radarr events
    required = ["movie", "release"]
    missing = [k for k in required if k not in payload or payload.get(k) in (None, {})]
    if missing:
        logger.error("radarr_webhook: missing keys in payload: %s", missing)
        return jsonify({"ok": False, "error": "missing_keys", "missing": missing}), 400

    movie = payload.get("movie")
    release = payload.get("release")
    movie_file = payload.get("movieFile")

    title = movie.get("title")
    radarr_id = movie.get("id")
    download_id = payload.get("downloadId")

    # If there's no downloadId, treat this event as non-actionable (Radarr test/event), avoid 400 spam.
    if not download_id:
        logger.info("radarr_webhook: no downloadId present — ignoring event (movie=%s, radarr_id=%s)", title, radarr_id)
        return jsonify({"ok": False, "message": "no downloadId — ignored"}), 200

    # Additional defensive checks
    if title is None or radarr_id is None:
        logger.error(
            "radarr_webhook: missing subkeys movie.title/movie.id; movie.title=%s radarr_id=%s",
            title, radarr_id
        )
        return jsonify({
            "ok": False,
            "error": "missing_subkeys",
            "details": "movie.title and movie.id are required"
        }), 400

    # If movieFile missing -> fallback minimal (log it)
    if not movie_file:
        logger.info("radarr_webhook: movieFile missing -> using fallback from release/movie")
        movie_file = {
            "relativePath": release.get("releaseTitle") or movie.get("title") or f"radarr-{radarr_id}",
            "size": release.get("size") or 0,
            "path": movie.get("folderPath") or ""
        }

    release_title = release.get("releaseTitle")

    # Build DTO (defensive)
    dto = {
        "radarr_id": str(radarr_id),
        "title": title,
        "image": movie.get("images", [{}])[0].get("remoteUrl"),
        "torrent": {
            "hash": download_id,
            "title": movie_file.get("relativePath"),
            "releaseTitle": release_title,
            "downloadClient": payload.get("downloadClient"),
            "downloadClientType": payload.get("downloadClientType"),
            "size": movie_file.get("size"),
            "quality": movie_file.get("quality") or release.get("quality"),
            "relativePath": movie_file.get("relativePath"),
            "path": movie_file.get("path"),
        },
    }

    try:
        result = service.import_completed_movie(dto)
        return jsonify({"ok": True, "result": result}), 200
    except Exception:
        logger.exception("radarr_webhook: unexpected error during processing")
        return jsonify({"ok": False, "error": "internal error"}), 500
