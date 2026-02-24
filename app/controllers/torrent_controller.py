from flask import jsonify
from app.logger import get_logger
from ..services.torrent_service import TorrentService

logger = get_logger(__name__)

def torrent_webhook(request, app):
    service = TorrentService(app)
    dto = {}
    try:
        dto = request.get_json(force=True)
    except Exception:
        logger.warning("torrent_webhook: invalid JSON payload")
        return jsonify({"ok": False, "error": "invalid_json"}), 400

    
    try:
        result = service.import_cross_seed(dto)
    except Exception:
        logger.exception("torrent_webhook: unexpected error during processing")
        return jsonify({"ok": False, "error": "internal error"}), 500

    # Robustesse : extraire champs utiles sans lever si absent
    linked = result.get("linked") if isinstance(result, dict) else None
    message = result.get("message") if isinstance(result, dict) else None
    torrent_name = result.get("torrent") if isinstance(result, dict) else None
    torrent_hash = result.get("hash") if isinstance(result, dict) else None
    cross_seed_id = result.get("cross_seed_id") if isinstance(result, dict) else None

    # Si le service ne renvoie pas explicitement 'linked', inférer (fallback)
    if linked is None:
        linked = bool(cross_seed_id)

    if linked:
        logger.info(
            "Import terminé du cross-seed — LINKED: torrent=%s hash=%s parent_id=%s message=%s",
            torrent_name or "<unknown>",
            torrent_hash or "<unknown>",
            cross_seed_id,
            message or ""
        )
        logger.info("\n---------------------------------------------------\n"
                    " Import terminé du cross-seed (parent trouvé / child lié)\n"
                    "---------------------------------------------------")
    else:
        # parent non trouvé ou link failed
        logger.warning(
            "Import terminé du cross-seed — NOT LINKED: torrent=%s hash=%s message=%s",
            torrent_name or "<unknown>",
            torrent_hash or "<unknown>",
            message or "no_parent_found"
        )
        logger.warning("\n---------------------------------------------------\n"
                       " Import terminé du cross-seed (parent NON trouvé ou lien échoué)\n"
                       "---------------------------------------------------")

    return jsonify({"ok": True, "result": result}), 200