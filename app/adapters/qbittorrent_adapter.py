# adapters/qbitadapter.py
from typing import List, Optional, Any, Dict
from urllib.parse import urlparse
from app.logger import get_logger
from ..config import QBIT_HOST, QBIT_USER, QBIT_PASS, VERIFY_SSL
import qbittorrentapi

logger = get_logger(__name__)


class QbittorrentAdapter:
    
    def __init__(
        self,
        host: str = QBIT_HOST,
        user: Optional[str] = QBIT_USER,
        password: Optional[str] = QBIT_PASS,
        dry_run: bool = False,
    ):
        self.base = (host or "").rstrip("/")
        self.user = user
        self.password = password
        self.logger = logger
        self.dry_run = dry_run
        self.client: Optional[qbittorrentapi.Client] = None
        self._logged = False

    def _init_client(self) -> None:
        if self.client:
            return
        self.client = qbittorrentapi.Client(
            host=self.base,
            username=self.user,
            password=self.password,
            VERIFY_WEBUI_CERTIFICATE= VERIFY_SSL
        )

    def login(self) -> bool:
        if self._logged:
            self.logger.debug("[qBittorrent] login: already logged")
            return True
        if self.dry_run:
            self.logger.debug("[qBittorrent] [DRY_RUN] login skipped")
            self._logged = True
            return True

        try:
            self._init_client()
            self.client.auth_log_in()
            self._logged = True
            self.logger.info("[qBittorrent] login success")
            return True
        except qbittorrentapi.LoginFailed as e:
            self.logger.exception("[qBittorrent] login failed (auth error): %s", e)
            raise
        except Exception:
            self.logger.exception("[qBittorrent] login failed (unexpected)")
            raise


    def info_map(self, hashes: List[str]) -> Dict[str, dict]:
        if not hashes:
            return {}
        hashes_norm = [h.lower().strip() for h in hashes if h]
        if not hashes_norm:
            return {}

        if self.dry_run:
            out = {}
            for h in hashes_norm:
                out[h] = {"name": f"torrent_{h[:8]}...", "hash": h}
            return out
        try:
            self.login()
        except Exception:
            self.logger.exception("[qBittorrent] info_map: login failed")
            raise

        try:
            torrents = self.client.torrents_info(torrent_hashes=hashes_norm)
            out: Dict[str, dict] = {}
            for t in torrents:
                thash = getattr(t, "hash", None) or t.get("hash") if isinstance(t, dict) else None
                if not thash:
                    continue
                out[thash.lower()] = dict(t) if isinstance(t, dict) else t.__dict__
            return out
        except Exception:
            self.logger.exception("[qBittorrent] info_map: failed to fetch torrents info")
            raise
        

    def delete_torrents(self, hashes: List[str] | str, delete_files: bool = True) -> Dict[str, Any]:
        if isinstance(hashes, str):
            hashes = [hashes]
        hashes_norm = [h.lower().strip() for h in hashes if h]
        if not hashes_norm:
            return {"error": None, "deleted": [], "failed": [], "absent": []}

        if self.dry_run:
            deleted = [(h, f"torrent_{h[:8]}...") for h in hashes_norm]
            return {"error": None, "deleted": deleted, "failed": [], "absent": []}

        try:
            self.login()
        except Exception:
            self.logger.exception("[qBittorrent] delete_torrents: login failed")
            return {"error": "login_failed", "deleted": [], "failed": [], "absent": []}

        deleted = []
        failed = []
        absent = []

        try:
            info_before = self.info_map(hashes_norm)
        except Exception:
            info_before = {}

        for h in hashes_norm:
            try:
                if h not in info_before:
                    absent.append(h)
                    self.logger.info("[qBittorrent] absent (not present) hash=%s", h)
                    continue
                try:
                    self.client.torrents_delete(torrent_hashes=h, delete_files=bool(delete_files))
                except Exception as e:
                    self.logger.exception("[qBittorrent] delete API call failed for hash=%s: %s", h, e)
                    name = (info_before.get(h) or {}).get("name")
                    failed.append((h, name))
                    continue
                try:
                    info_after = self.info_map([h])
                except Exception:
                    info_after = {}

                name_before = (info_before.get(h) or {}).get("name", f"<{h[:12]}>")
                if h not in info_after:
                    deleted.append((h, name_before))
                    self.logger.info("[qBittorrent] deleted hash=%s name=%s", h, name_before)
                else:
                    failed.append((h, name_before))
                    self.logger.warning("[qBittorrent] failed to delete hash=%s name=%s", h, name_before)

            except Exception as e:
                self.logger.exception("[qBittorrent] unexpected error handling hash=%s: %s", h, e)
                try:
                    name_try = (info_before.get(h) or {}).get("name", None)
                except Exception:
                    name_try = None
                failed.append((h, name_try))

        return {"error": None, "deleted": deleted, "failed": failed, "absent": absent}
           

    def get_indexer_from_hash(self, torrent_hash: str) -> Optional[str]:
        if not torrent_hash:
            self.logger.info("[qBittorrent] no hash given, cannot search torrent indexer")
            return None

        try:
            trackers = self.client.torrents_trackers(torrent_hash=torrent_hash)
            if not trackers:
                return None

            for tracker in trackers:
                url = getattr(tracker, "url", None) or (tracker.get("url") if isinstance(tracker, dict) else None)
                if not url:
                    continue
                parsed = urlparse(url)
                hostname = (parsed.hostname or "").lower()

                if "tracker.torr9.xyz" in hostname:
                    return "torr9"
                if "la-cale.space" in hostname or "tracker.la-cale.space" in hostname:
                    return "lacale"
                if "p2p-world.net" in hostname:
                    return "ygg"
                if "nyaa.tracker.wf" in hostname:
                    return "nyaa"

            return None
        except Exception as e:
            self.logger.exception("[qBittorrent] failed to retrieve indexer for hash=%s: %s", torrent_hash, e)
            return None