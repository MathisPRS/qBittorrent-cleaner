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
        hashes = [ (h or "").lower().strip() for h in hashes if h ]
        if not hashes:
            return {"error": "no_hashes", "deleted": [], "failed": [], "absent": [], "request": None, "response": None}

        # dry-run simulation
        if self.dry_run:
            deleted = [(h, f"torrent_{h[:8]}...") for h in hashes]
            req = {"url": None, "data": {"hashes": "|".join(hashes), "deleteFiles": str(delete_files)}}
            resp = {"status_code": None, "text": "[DRY_RUN]", "json": None, "headers": None}
            # Log simulated behavior
            self.logger.info("[qBittorrent] [DRY_RUN] delete_torrents request=%s response=%s", req, resp)
            return {"deleted": deleted, "failed": [], "absent": [], "request": req, "response": resp}

        # ensure logged
        try:
            self.login()
        except Exception as e:
            self.logger.exception("[qBittorrent] delete_torrents: login failed")
            return {"error": "login_failed", "exception": str(e), "deleted": [], "failed": [], "absent": [], "request": None, "response": None}

        # snapshot before (get names)
        try:
            present_before = self.info_map(hashes)
        except Exception:
            present_before = {}

        url = urljoin(self.base, "api/v2/torrents/delete")
        data = {"hashes": "|".join(hashes), "deleteFiles": "true" if delete_files else "false"}

        # Perform delete
        try:
            r = self.session.post(url, data=data, timeout=REQ_TIMEOUT)
            resp_text = r.text or ""
            parsed = None
            try:
                parsed = r.json()
            except Exception:
                parsed = None

            self.logger.debug("[qBittorrent] delete_torrents: response status=%s", r.status_code)
            self.logger.debug("[qBittorrent] delete_torrents: response headers=%s", dict(r.headers))
            # show parsed json if available else text preview
            self.logger.debug("[qBittorrent] delete_torrents: response body_preview=%s", (parsed if parsed is not None else resp_text[:2000]))

            # small sleep to let qB update its state
            time.sleep(0.6)

            try:
                present_after = self.info_map(hashes)
            except Exception:
                present_after = {}

            deleted: List[Tuple[str, str]] = []
            failed: List[Tuple[str, str]] = []
            absent: List[str] = []

            for h in hashes:
                name = (present_before.get(h, {}) or {}).get("name", f"<{h[:12]}>")
                if h not in present_before:
                    absent.append(h)
                elif h not in present_after:
                    deleted.append((h, name))
                else:
                    failed.append((h, name))

            req = {"url": url, "data": data}
            resp = {"status_code": r.status_code, "text": resp_text, "json": parsed, "headers": dict(r.headers)}

            # More expressive logging
            if deleted:
                self.logger.info("[qBittorrent] [bulk] deleted: %s", [n for _, n in deleted])
            if failed:
                self.logger.warning("[qBittorrent] [bulk] failed: %s", [n for _, n in failed])
            if absent:
                self.logger.info("[qBittorrent] [bulk] absent: %d", len(absent))

            result = {
                "deleted": deleted,
                "failed": failed,
                "absent": absent,
                "request": req,
                "response": resp
            }
            return result

        except RequestException as e:
            resp = getattr(e, "response", None)
            status = getattr(resp, "status_code", None)
            text = getattr(resp, "text", None)
            self.logger.exception("[qBittorrent] delete_torrents: request failed")
            return {
                "error": str(e),
                "status_code": status,
                "text": text,
                "deleted": [],
                "failed": [],
                "absent": [],
                "request": {"url": url, "data": data},
                "response": {"status_code": status, "text": text, "json": None, "headers": None}
            }
        except Exception as e:
            self.logger.exception("[qBittorrent] delete_torrents: unexpected exception")
            return {"error": str(e), "deleted": [], "failed": [], "absent": [], "request": {"url": url, "data": data}, "response": None}
