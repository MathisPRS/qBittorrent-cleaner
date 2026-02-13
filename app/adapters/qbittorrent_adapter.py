import requests
from urllib.parse import urljoin


class QbittorrentAdapter:

    def __init__(self, host, user, password, logger=None, dry_run=False):
        self.base = host.rstrip("/") + "/"
        self.user = user
        self.password = password
        self.logger = logger
        self.dry_run = dry_run
        self.session = requests.Session()
        self._logged = False

    
    def login(self):
        if self._logged:
            return True
        url = urljoin(self.base, "api/v2/auth/login")
        response = self.session.post(
            url,
            data={
                "username": self.user,
                "password": self.password
            },
            timeout=10
        )
        response.raise_for_status()
        if response.text.strip() != "Ok.":
            raise RuntimeError("qBittorrent login failed")
        self._logged = True
        if self.logger:
            self.logger.info("qBittorrent login success")

        return True
    

    def ensure_logged(self):
        if not self._logged:
            self.login()

   
    def get_torrents(self):
        self.ensure_logged()
        url = urljoin(self.base, "api/v2/torrents/info")
        response = self.session.get(url, timeout=10)
        response.raise_for_status()

        return response.json()
    

    def get_torrent_by_hash(self, hash):
        self.ensure_logged()
        torrents = self.get_torrents()
        for torrent in torrents:
            if torrent.get("hash", "").lower() == hash.lower():
                return torrent

        return None

   
    def delete_torrents(self, hashes, delete_files=False):
        if isinstance(hashes, str):
            hashes = [hashes]
        hashes = [h for h in hashes if h]

        if not hashes:
            raise ValueError("No hashes provided for deletion")

        if self.dry_run:
            if self.logger:
                self.logger.info("[DRY_RUN] Would delete torrents: %s", hashes)
            return "DRY_RUN"

        self.ensure_logged()

        url = urljoin(self.base, "api/v2/torrents/delete")
        response = self.session.post(
            url,
            data={
                "hashes": ",".join(hashes),
                "deleteFiles": "true" if delete_files else "false"
            },
            timeout=10
        )

        response.raise_for_status()
        if self.logger:
            self.logger.info("Deleted torrents: %s", hashes)

        return response.text
