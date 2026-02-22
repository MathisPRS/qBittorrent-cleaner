from typing import Dict, Optional
from ..services.commun_service import CommunService
from ..repositories.torrents_repo import TorrentsRepo
from ..adapters.gotify_adapter import notify_gotify
from app.logger import get_logger

logger = get_logger(__name__)


class TorrentService:

    def __init__(self, app):
        self.app = app
        self.commun_service = CommunService(app)
        self.torrents_repo = TorrentsRepo()

        self.parent_torrent: Optional[int] = None
        self.cross_seed_torrent_name: Optional[str] = None
        self.cross_seed_torrent_hash: Optional[str] = None
        

    def import_cross_seed(self, dto: Dict) -> Dict:
        """
        DTO attendu : { "name": ..., "hash": ... }
        Comportement : si l'enfant existe déjà, on met quand même à jour ses infos (name, cross_seed_id).
        """

        self.cross_seed_torrent_name = dto.get("name")
        self.cross_seed_torrent_hash = dto.get("hash")

        # Anti-casse basique
        if not self.cross_seed_torrent_name or not self.cross_seed_torrent_hash:
            logger.warning("import_cross_seed: missing name or hash in dto")
            return {
                "torrent": None,
                "hash": None,
                "cross_seed_id": None,
                "linked": False,
                "message": "invalid_payload"
            }

        # Créer / récupérer le torrent enfant (peut retourner existant)
        cross_seed_torrent = self.commun_service.ensure_torrent_exists(
            self.cross_seed_torrent_hash,
            self.cross_seed_torrent_name
        )

        # extraire id/hash/name de l'enfant si possible
        child_id = getattr(cross_seed_torrent, "id", None)
        torrent_name = getattr(cross_seed_torrent, "name", self.cross_seed_torrent_name)
        torrent_hash = getattr(cross_seed_torrent, "hash", self.cross_seed_torrent_hash)

        # Trouver le parent en excluant l'enfant (évite le self-link si l'enfant a déjà id)
        parent = self.torrents_repo.get_parent_by_name(self.cross_seed_torrent_name, exclude_id=child_id)
        parent_id = parent.id if parent else None

        linked_torrent = None
        linked = False
        result_message = "none"

        if parent_id is None:
            # pas de parent -> on ne peut pas lier
            logger.info("import_cross_seed: no parent found for name=%s (child_id=%s)", self.cross_seed_torrent_name, child_id)
            result_message = "no_parent_found"
        else:
            # On appelle set_cross_seed_parent systématiquement : 
            # si l'enfant existe déjà, on mettra à jour son cross_seed_id et éventuellement son name.
            linked_torrent = self.torrents_repo.set_cross_seed_parent(
                child_hash=torrent_hash,
                parent_id=parent_id,
                child_name=torrent_name
            )

            if linked_torrent:
                # si tout s'est bien passé on considère linked True (même si déjà identique avant)
                linked = True
                result_message = "linked"
                self.parent_torrent = parent_id
                logger.info("import_cross_seed: child (hash=%s) linked/updated to parent_id=%s", torrent_hash, parent_id)
            else:
                linked = False
                result_message = "link_failed"
                logger.warning("import_cross_seed: failed to link child (hash=%s) to parent_id=%s", torrent_hash, parent_id)

        # Gotify only on successful link
        if linked:
            try:
                response = notify_gotify(
                    title=f"Ajout Cross seed reussi",
                    lines=[f"Nom du cross-seed : {torrent_name}"]
                )
                if response and response.get("ok"):
                    logger.info("Gotify notification sent successfully")
                else:
                    logger.warning("Gotify returned failure response: %s", response)
            except Exception:
                logger.exception("Gotify unexpected error")

        # Préparer la réponse JSON-serializable
        try:
            final_hash = str(torrent_hash) if torrent_hash is not None else None
        except Exception:
            final_hash = self.cross_seed_torrent_hash

        try:
            final_name = str(torrent_name) if torrent_name is not None else None
        except Exception:
            final_name = self.cross_seed_torrent_name

        returned_parent_id = int(parent_id) if linked and parent_id is not None else None

        response = {
            "torrent": final_name,
            "hash": final_hash,
            "cross_seed_id": returned_parent_id,
            "linked": linked,
            "message": result_message
        }

        return response