from flask import jsonify
from app.logger import get_logger
from ..services.radarr_services import RadarrService

def radarr_webhook(request, app):
    logger = get_logger(__name__, app=app)
    service = RadarrService(app)

    payload = request.get_json(silent=True)
    if not payload:
        logger.warning("radarr_webhook: invalid or empty json payload")
        return jsonify({"ok": False, "error": "invalid json"}), 400

    required = ("movie", "release")
    missing = [k for k in required if not payload.get(k)]
    if missing:
        logger.error("radarr_webhook: missing keys in payload: %s", missing)
        return jsonify({"ok": False, "error": "missing_keys", "missing": missing}), 400

    movie = payload["movie"]
    release = payload["release"]
    movie_file = payload.get("movieFile")

    title = movie.get("title")
    radarr_id = movie.get("id")
    source_path = (movie_file or {}).get("sourcePath")
    download_id = payload.get("downloadId")
    indexer = release.get("indexer")

    if not download_id:
        logger.info(
            "radarr_webhook: no downloadId present — ignoring event (movie=%s radarr_id=%s)",
            title, radarr_id
        )
        return jsonify({"ok": False, "message": "no downloadId — ignored"}), 200
    
    if not indexer:
        logger.info("radarr_webhook: no indexer value present")
        indexer = None

    if not title or radarr_id is None:
        logger.error(
            "radarr_webhook: missing movie.title or movie.id (title=%s id=%s)",
            title, radarr_id
        )
        return jsonify({
            "ok": False,
            "error": "missing_subkeys",
            "details": "movie.title and movie.id are required"
        }), 400

    if not movie_file:
        logger.info("radarr_webhook: movieFile missing -> using fallback from release/movie")
        movie_file = {
            "relativePath": release.get("releaseTitle") or title or f"radarr-{radarr_id}",
            "size": release.get("size") or 0,
            "path": movie.get("folderPath") or ""
        }

    dto = {
        "radarr_id": str(radarr_id),
        "title": title,
        "image": (movie.get("images") or [{}])[0].get("remoteUrl"),
        "torrent": {
            "hash": download_id,
            "title": movie_file.get("relativePath"),
            "releaseTitle": release.get("releaseTitle"),
            "downloadClient": payload.get("downloadClient"),
            "downloadClientType": payload.get("downloadClientType"),
            "size": movie_file.get("size"),
            "quality": release.get("quality"),
            "sourcePath": source_path,
            "indexer": indexer
        },
    }

    try:
        result = service.import_completed_movie(dto)

        if not isinstance(result, dict):
            logger.error("radarr_webhook: service returned unexpected type: %s", type(result))
            return jsonify({"ok": False, "error": "invalid_service_response"}), 500

        #Logging reponse action
        action = result.get("action")
        action_map = {
            "created": (201, "info", f"Film créé avec succès : {title}"),
            "updated": (200, "info", f"Film mis à jour : {title}"),
            "ignored": (200, "info", f"Film ignoré (aucune action requise) : {title}"),
            "no_parent_found": (409, "warning", f"Parent introuvable pour : {title}"),
            "error": (422, "error", f"Erreur métier lors du traitement du film : {title}"),
        }

        status, level, msg = action_map.get(
            action,
            (200, "info", f"Import terminé (action={action}) : {title}")
        )
        _log_block(logger, level, msg)

        return jsonify({"ok": action != "error", "result": result}), status

    except Exception:
        logger.exception("radarr_webhook: unexpected error during processing")
        return jsonify({"ok": False, "error": "internal error"}), 500
    
def _log_block(logger, level: str, message: str):
    LOG_SEPARATOR = "-" * 65
    log_fn = getattr(logger, level)
    log_fn("\n%s\n%s\n%s", LOG_SEPARATOR, message, LOG_SEPARATOR)
