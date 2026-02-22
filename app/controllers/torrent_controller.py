from flask import jsonify
from app.logger import get_logger
from ..services.torrent_service import TorrentService

def torrent_webhook(request, app):
    logger = get_logger(__name__, app=app)
    service = TorrentService(app)

    payload = request.get_json(silent=True)
    if payload is None:
        logger.warning("torrent_webhook: invalid json payload")
        return jsonify({"ok": False, "error": "invalid json"}), 400

    # Pour ton cas métier on exige series, episodes et episodeFiles
    required = ["name", "hash"]
    missing = [k for k in required if k not in payload or not payload.get(k)]
    if missing:
        logger.error("torrent_webhook: missing keys in payload: %s", missing)
        return jsonify({"ok": False, "error": "missing_keys", "missing": missing}), 400

    name_torrent = payload.get("name")
    hash_torrent = payload.get("hash", [])
    dto = {
        "name" : name_torrent,
        "hash" : hash_torrent,
    }
    try:
        result = service.import_cross_seed(dto)
        logger.info(f"\n---------------------------------------------------\n"+
                    " Import terminé du cross-seed" 
                    +"\n---------------------------------------------------")
        return jsonify({"ok": True, "result": result}), 200
    except Exception:
        logger.exception("torrent_webhook: unexpected error during processing")
        return jsonify({"ok": False, "error": "internal error"}), 500
    