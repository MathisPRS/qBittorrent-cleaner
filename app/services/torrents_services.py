# app/services/torrent_service.py
from typing import Dict, Optional
from .commun_services import CommunService
from ..repositories.torrents_repo import TorrentsRepo
from ..adapters.gotify_adapter import notify_gotify
from app.logger import get_logger

logger = get_logger(__name__)


class TorrentService:

    def __init__(self, app):
        self.app = app
        self.commun_service = CommunService(app)
        self.torrents_repo = TorrentsRepo()

        # état stocké
        self.parent_torrent: Optional[int] = None
        self.cross_seed_torrent_name: Optional[str] = None
        self.cross_seed_torrent_hash: Optional[str] = None
        self.parent_torrent_hash: Optional[str] = None

    def import_cross_seed(self, dto: Dict) -> Dict:
        self.cross_seed_torrent_name = dto.get("name")
        self.cross_seed_torrent_hash = dto.get("hash")
        self.parent_torrent_hash = dto.get("parent_hash") or None

        if not self.cross_seed_torrent_name or not self.cross_seed_torrent_hash:
            logger.warning("import_cross_seed: missing name or hash in dto")
            return {
                "torrent": None,
                "hash": None,
                "cross_seed_id": None,
                "linked": False,
                "message": "invalid_payload"
            }

        try:
            parent = self.torrents_repo.get_parent_by_name(
                name=self.cross_seed_torrent_name,
                exclude_id=None,                      
                parent_hash=self.parent_torrent_hash  # peut être None
            )
            parent_id = parent.id if parent else None
        except Exception:
            logger.exception("import_cross_seed: get_parent_by_name failed for name=%s parent_hash=%s",
                             self.cross_seed_torrent_name, self.parent_torrent_hash)
            parent = None
            parent_id = None

        # si parent introuvable -> on n'écrit rien ; notify Gotify et on renvoie
        if parent_id is None:
            logger.info("import_cross_seed: parent NOT FOUND for name=%s parent_hash=%s — will not create cross-seed",
                        self.cross_seed_torrent_name, self.parent_torrent_hash)
            # Gotify: alerte pour intervention manuelle
            try:
                resp = notify_gotify(
                    title="Cross-seed non créé - Parent not found",
                    lines=[
                        f"Nom : {self.cross_seed_torrent_name}",
                        f"Hash : {self.cross_seed_torrent_hash}",
                        "Parent introuvable — le cross-seed n'a pas été créé."
                    ]
                )
                if resp and resp.get("ok"):
                    logger.info("Gotify: no-parent notification sent")
                else:
                    logger.warning("Gotify: no-parent notification returned not ok: %s", resp)
            except Exception:
                logger.exception("Gotify: exception while sending no-parent notification")

            return {
                "torrent": str(self.cross_seed_torrent_name),
                "hash": str(self.cross_seed_torrent_hash),
                "cross_seed_id": None,
                "linked": False,
                "message": "parent_not_found_no_create"
            }

        # 2) parent trouvé -> créer l'enfant puis le lier
        try:
            child = self.commun_service.ensure_torrent_exists(
                self.cross_seed_torrent_hash,
                self.cross_seed_torrent_name
            )
        except Exception:
            logger.exception("import_cross_seed: ensure_torrent_exists failed for hash=%s name=%s",
                             self.cross_seed_torrent_hash, self.cross_seed_torrent_name)
            return {
                "torrent": self.cross_seed_torrent_name,
                "hash": self.cross_seed_torrent_hash,
                "cross_seed_id": None,
                "linked": False,
                "message": "ensure_failed"
            }

        # extraire infos enfant si disponibles
        child_hash = getattr(child, "hash", None) or self.cross_seed_torrent_hash
        child_name = getattr(child, "name", None) or self.cross_seed_torrent_name

        # tenter de lier l'enfant au parent
        linked = False
        result_message = "none"
        try:
            linked_torrent = self.torrents_repo.set_cross_seed_parent(
                child_hash=child_hash,
                parent_id=parent_id,
                child_name=child_name
            )
            if linked_torrent:
                linked = True
                result_message = "linked"
                self.parent_torrent = parent_id
                logger.info("import_cross_seed: child created/linked: child_hash=%s parent_id=%s", child_hash, parent_id)
            else:
                linked = False
                result_message = "link_failed"
                logger.warning("import_cross_seed: set_cross_seed_parent returned None for child_hash=%s parent_id=%s",
                               child_hash, parent_id)
        except Exception:
            logger.exception("import_cross_seed: set_cross_seed_parent raised for child_hash=%s parent_id=%s",
                             child_hash, parent_id)
            linked = False
            result_message = "link_exception"

        # 3) notifications Gotify selon le cas
        try:
            if linked:
                resp = notify_gotify(
                    title=f"Ajout Cross seed reussi: {child_name}",
                    lines=[f"Nom du cross-seed : {child_name}", f"Hash : {child_hash}"]
                )
                if resp and resp.get("ok"):
                    logger.info("Gotify: linked notification ok")
                else:
                    logger.warning("Gotify: linked notification returned not ok: %s", resp)
            else:
                # link failed -> notify for manual check (optional)
                resp = notify_gotify(
                    title="Cross-seed link failed",
                    lines=[
                        f"Nom : {child_name}",
                        f"Hash : {child_hash}",
                        f"Parent id attendu : {parent_id}",
                        "Action requise: vérifier manuellement."
                    ]
                )
                if resp and resp.get("ok"):
                    logger.info("Gotify: link-failed notification sent")
                else:
                    logger.warning("Gotify: link-failed notification returned not ok: %s", resp)
        except Exception:
            logger.exception("Gotify: unexpected error in notification logic")

        # 4) réponse JSON-serializable
        try:
            final_name = str(child_name) if child_name is not None else str(self.cross_seed_torrent_name)
        except Exception:
            final_name = self.cross_seed_torrent_name

        try:
            final_hash = str(child_hash) if child_hash is not None else str(self.cross_seed_torrent_hash)
        except Exception:
            final_hash = self.cross_seed_torrent_hash

        returned_parent_id = int(parent_id) if linked and parent_id is not None else None

        return {
            "torrent": final_name,
            "hash": final_hash,
            "cross_seed_id": returned_parent_id,
            "linked": bool(linked),
            "message": result_message
        }