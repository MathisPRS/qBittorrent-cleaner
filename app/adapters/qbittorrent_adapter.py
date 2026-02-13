# adapters/qbitadapter.py
from typing import List, Optional, Any
from urllib.parse import urljoin
import requests
from app.logger import get_logger


class QbittorrentAdapter:
   
    def __init__(
        self,
        host: str,
        user: str,
        password: str,
        logger=None,
        dry_run: bool = False,
    ):
        self.base = host.rstrip("/") + "/"
        self.user = user
        self.password = password
        # si aucun logger fourni, on récupère un logger configuré
        self.logger = logger or get_logger(__name__)
        self.dry_run = dry_run
        self.session = requests.Session()
        self._logged = False

    def login(self) -> bool:
        if self._logged:
            self.logger.debug("login: déjà connecté, skip")
            return True

        url = urljoin(self.base, "api/v2/auth/login")
        self.logger.debug("login: POST %s", url)
        try:
            response = self.session.post(
                url,
                data={"username": self.user, "password": self.password},
                timeout=10,
            )
            response.raise_for_status()
        except Exception:
            self.logger.exception("login: échec de la requête vers qBittorrent")
            raise

        text = (response.text or "").strip()
        if text != "Ok.":
            self.logger.error("login: réponse inattendue: %r", text)
            raise RuntimeError("qBittorrent login failed")

        self._logged = True
        self.logger.info("qBittorrent login success")
        return True

    def ensure_logged(self) -> None:
        if not self._logged:
            self.login()

    def get_torrents(self) -> List[Any]:
        
        self.ensure_logged()
        url = urljoin(self.base, "api/v2/torrents/info")
        self.logger.debug("get_torrents: GET %s", url)
        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            torrents = response.json()
        except Exception:
            self.logger.exception("get_torrents: impossible de récupérer les torrents")
            raise

        self.logger.debug("get_torrents: récupéré %d torrents", len(torrents) if hasattr(torrents, "__len__") else -1)
        return torrents

    def get_torrent_by_hash(self, hash: str) -> Optional[dict]:
        if not hash:
            self.logger.debug("get_torrent_by_hash: hash vide fourni")
            return None

        try:
            torrents = self.get_torrents()
        except Exception:
            self.logger.debug("get_torrent_by_hash: échec lors de la récupération des torrents")
            raise

        target = None
        for torrent in torrents:
            th = (torrent.get("hash") or "").lower()
            if th == hash.lower():
                target = torrent
                break

        if target:
            self.logger.debug("get_torrent_by_hash: torrent trouvé pour hash=%s", hash)
        else:
            self.logger.debug("get_torrent_by_hash: aucun torrent pour hash=%s", hash)

        return target

    def delete_torrents(self, hashes, delete_files: bool = False) -> str:
        # Normalisation
        if isinstance(hashes, str):
            hashes = [hashes]
        hashes = [h for h in hashes if h]

        if not hashes:
            self.logger.error("delete_torrents: aucune hash fournie")
            raise ValueError("No hashes provided for deletion")

        if self.dry_run:
            self.logger.info("[DRY_RUN] Would delete torrents: %s (delete_files=%s)", hashes, delete_files)
            return "DRY_RUN"

        self.ensure_logged()

        url = urljoin(self.base, "api/v2/torrents/delete")
        data = {"hashes": ",".join(hashes), "deleteFiles": "true" if delete_files else "false"}
        self.logger.debug("delete_torrents: POST %s data=%s", url, {"hashes_count": len(hashes), "deleteFiles": delete_files})

        try:
            response = self.session.post(url, data=data, timeout=10)
            response.raise_for_status()
        except Exception:
            self.logger.exception("delete_torrents: échec suppression torrents %s", hashes)
            raise

        self.logger.info("Deleted torrents: %s (delete_files=%s)", hashes, delete_files)
        return response.text
