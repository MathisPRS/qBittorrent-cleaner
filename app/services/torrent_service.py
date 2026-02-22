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

        self.cross_seed_torrent_name = dto.get("name")
        self.cross_seed_torrent_hash = dto.get("hash")

        if not self.cross_seed_torrent_name or not self.cross_seed_torrent_hash:
            logger.warning("import_cross_seed: missing name or hash in dto")
            return {
                "torrent": None,
                "hash": None,
                "cross_seed_id": None
            }

        # Création / récupération enfant
        cross_seed_torrent = self.commun_service.ensure_torrent_exists(
            self.cross_seed_torrent_hash,
            self.cross_seed_torrent_name
        )

        torrent_name = getattr(cross_seed_torrent, "name", self.cross_seed_torrent_name)
        torrent_hash = getattr(cross_seed_torrent, "hash", self.cross_seed_torrent_hash)

        parent = self.torrents_repo.get_parent_by_name(self.cross_seed_torrent_name)
        parent_id = parent.id if parent else None

        linked = False

        if parent_id:
            linked_torrent = self.torrents_repo.set_cross_seed_parent(
                torrent_hash,
                parent_id
            )

            if linked_torrent:
                linked = True
                self.parent_torrent = parent_id
                logger.info(
                    "Cross-seed linked successfully: child_hash=%s -> parent_id=%s",
                    torrent_hash,
                    parent_id
                )
            else:
                logger.warning(
                    "Cross-seed link failed for child_hash=%s parent_id=%s",
                    torrent_hash,
                    parent_id
                )
        else:
            logger.info(
                "No parent found for torrent name=%s",
                self.cross_seed_torrent_name
            )

        if linked:
            try:
                response = notify_gotify(
                    title="Ajout Cross seed reussi",
                    lines=[f"Nom du cross-seed : {torrent_name}"]
                )

                if response and response.get("ok"):
                    logger.info("Gotify notification sent successfully")
                else:
                    logger.warning("Gotify notification failed: %s", response)

            except Exception as e:
                logger.exception("Gotify unexpected error: %s", e)

        return {
            "torrent": str(torrent_name),
            "hash": str(torrent_hash),
            "cross_seed_id": int(parent_id) if parent_id else None
        }