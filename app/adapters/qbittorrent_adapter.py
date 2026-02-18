# adapters/qbitadapter.py
from typing import List, Optional, Any, Dict, Tuple
from urllib.parse import urljoin
import time
import requests
from requests.exceptions import RequestException
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from app.logger import get_logger
from ..config import QBIT_HOST

REQ_TIMEOUT = 12

logger = get_logger(__name__)


class QbittorrentAdapter:
   
    def __init__(
        self,
        host: str = QBIT_HOST,
        user: Optional[str] = None,
        password: Optional[str] = None,
        logger_obj=None,
        dry_run: bool = False,
    ):
        self.base = (host or "").rstrip("/") + "/"
        self.user = user
        self.password = password
        # use provided logger or module logger
        self.logger = logger_obj or logger
        self.dry_run = dry_run

        self.session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=(429, 502, 503, 504),
            allowed_methods=frozenset(['GET', 'POST', 'PUT', 'DELETE', 'HEAD'])
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        self._logged = False

    def login(self) -> bool:
        if self._logged:
            self.logger.debug("[qBittorrent] login: already logged")
            return True
        if self.dry_run:
            self.logger.debug("[qBittorrent] [DRY_RUN] login skipped")
            self._logged = True
            return True

        url = urljoin(self.base, "api/v2/auth/login")
        self.logger.debug("[qBittorrent] login: POST %s", url)
        try:
            r = self.session.post(
                url, data={"username": self.user, "password": self.password}, timeout=REQ_TIMEOUT
            )
            # log minimal preview but never log credentials
            self.logger.debug("[qBittorrent] login: status=%s body_preview=%s", r.status_code, (r.text or "")[:1000])
            r.raise_for_status()
        except RequestException as e:
            self.logger.exception("[qBittorrent] login: request failed")
            raise

        # qB returns "Ok." usually; be tolerant
        body = (r.text or "").strip()
        if body not in ("Ok.", "OK", "ok", "Ok"):
            raise RuntimeError(f"qBittorrent login failed: {body!r} (status={r.status_code})")
        self._logged = True
        self.logger.info("[qBittorrent] qBittorrent login success")
        return True

    def info_map(self, hashes: List[str]) -> Dict[str, dict]:
        if not hashes:
            return {}
        hashes_norm = [ (h or "").lower().strip() for h in hashes if h ]
        if not hashes_norm:
            return {}

        if self.dry_run:
            out = {}
            for h in hashes_norm:
                out[h] = {"name": f"torrent_{h[:8]}...", "hash": h}
            return out

        params = {"hashes": "|".join(hashes_norm)}
        url = urljoin(self.base, "api/v2/torrents/info")
        try:
            r = self.session.get(url, params=params, timeout=REQ_TIMEOUT)
            self.logger.debug("[qBittorrent] info_map: GET %s params=%s -> status=%s", url, params, r.status_code)
            r.raise_for_status()
            out = {}
            for t in r.json():
                out[(t.get("hash") or "").lower()] = t
            return out
        except Exception:
            self.logger.exception("[qBittorrent] info_map: failed to fetch torrents info")
            raise

    def delete_torrents(self, hashes, delete_files: bool = True, max_retry: int = 2) -> Dict[str, Any]:
        
        if isinstance(hashes, str):
            hashes = [hashes]
        if not hashes:
            return {"error": None, "deleted": [], "failed": [], "absent": []}

        try:
            self.login()
        except Exception as e:
            self.logger.exception("[qBittorrent] delete_torrents: login failed")
            return {"error": "login_failed", "deleted": [], "failed": [], "absent": []}

        deleted = []
        failed = []
        absent = []

        url = urljoin(self.base, "api/v2/torrents/delete")

        for h in hashes:
            try:
                try:
                    info_before = self.info_map([h])
                except Exception:
                    info_before = {}

                if not info_before or (h not in info_before):
                    # not found on qB -> mark absent, skip delete call
                    absent.append(h)
                    self.logger.info("[qBittorrent] absent (not present) hash=%s", h)
                    continue

                # present -> attempt to delete this single hash
                data = {"hashes": h, "deleteFiles": "true" if delete_files else "false"}
                try:
                    r = self.session.post(url, data=data, timeout=REQ_TIMEOUT)
                    # we don't need body; only status matters in combination with info_map
                except RequestException as e:
                    # network error for this hash -> mark failed and continue
                    self.logger.exception("[qBittorrent] network error when deleting hash=%s: %s", h, e)
                    name = (info_before.get(h) or {}).get("name", None)
                    failed.append((h, name))
                    continue
                
                # check after deletion
                try:
                    info_after = self.info_map([h])
                except Exception:
                    info_after = {}

                name_before = (info_before.get(h) or {}).get("name", f"<{h[:12]}>")

                if not info_after or (h not in info_after):
                    # successfully removed from qB
                    deleted.append((h, name_before))
                    self.logger.info("[qBittorrent] deleted hash=%s name=%s", h, name_before)
                else:
                    # still present -> deletion failed for this hash
                    failed.append((h, name_before))
                    self.logger.warning("[qBittorrent] failed to delete hash=%s name=%s", h, name_before)

            except Exception as e:
                # unexpected per-hash exception -> mark failed
                self.logger.exception("[qBittorrent] unexpected error handling hash=%s: %s", h, e)
                # try to get a name if possible (best-effort)
                try:
                    name_try = (info_before.get(h) or {}).get("name", None)
                except Exception:
                    name_try = None
                failed.append((h, name_try))

        # final logs (listes explicites)
        if deleted:
            self.logger.info("[qBittorrent] deleted hashes: %s", ", ".join([h for h, _ in deleted]))
        if absent:
            self.logger.info("[qBittorrent] absent hashes: %s", ", ".join(absent))
        if failed:
            self.logger.warning("[qBittorrent] failed hashes: %s", ", ".join([h for h, _ in failed]))

        return {"error": None, "deleted": deleted, "failed": failed, "absent": absent}

