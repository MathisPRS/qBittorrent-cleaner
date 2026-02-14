# adapters/gotify_adapter.py
from typing import List, Optional
import time
import requests
from requests.exceptions import RequestException, ConnectionError, Timeout
import urllib3
from app.logger import get_logger
from .. import config as app_config

logger = get_logger(__name__)


class GotifyAdapter:
    def __init__(self):
        self.enabled = getattr(app_config, "GOTIFY_ENABLED", False)
        self.url = getattr(app_config, "GOTIFY_URL", "") or ""
        if self.url:
            self.url = self.url.rstrip("/")
        self.token = getattr(app_config, "GOTIFY_TOKEN", "")
        self.priority = getattr(app_config, "GOTIFY_PRIO", 5)
        self.verify_ssl = getattr(app_config, "GOTIFY_VERIFY_SSL", True)
        self.title_default = getattr(app_config, "GOTIFY_TITLE", "Cleaner qBittorrent")
        self.dry_run = getattr(app_config, "DRY_RUN", False)

        # simple session reuse for perf
        self.session = requests.Session()

         # If SSL disabled → remove warnings
        if not self.verify_ssl:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        # simple retry parameters
        self._max_retries = 2
        self._backoff = 0.3

    def send(self, header: str, lines: Optional[List[str]] = None) -> dict:
        if not self.enabled or not self.url or not self.token:
            logger.debug("[Gotify] disabled or not configured; skipping")
            return {"ok": False, "error": "disabled_or_not_configured"}

        # pick first non-empty line as single-line body
        body_line = ""
        if lines:
            for l in lines:
                if l and l.strip():
                    body_line = l.strip()
                    break

        # prepare payload and echo
        payload = {"title": header or self.title_default, "message": body_line, "priority": self.priority}
        url = f"{self.url}/message"

        # dry-run support
        if self.dry_run:
            logger.info("[Gotify] [DRY_RUN] title=%s body=%s", payload["title"], payload["message"])
            return {"ok": True, "status_code": None, "dry_run": True, "payload": payload}

        # send with simple retry loop for transient errors
        last_exc = None
        for attempt in range(1, self._max_retries + 1):
            try:
                logger.debug("[Gotify] POST %s params=%s payload_preview=%s (attempt %d)", url, {"token": "*****"},
                             {"title": payload["title"], "message": (payload["message"] or "")[:200]}, attempt)
                r = self.session.post(url, params={"token": self.token}, json=payload, timeout=8,verify=self.verify_ssl)
                # If we get a response, capture status and text preview
                status = getattr(r, "status_code", None)
                text = (r.text or "")[:1000]
                if status and 200 <= status < 300:
                    logger.info("[Gotify] sent: title=%s status=%s", payload["title"], status)
                    return {"ok": True, "status_code": status, "payload": payload}
                else:
                    # Non-success HTTP status
                    logger.warning("[Gotify] send returned non-2xx status=%s text_preview=%s", status, text)
                    return {"ok": False, "status_code": status, "error": f"HTTP {status}", "response_text_preview": text, "payload": payload}
            except (ConnectionError, Timeout) as e:
                # transient network error: retry
                last_exc = e
                logger.warning("[Gotify] network error on attempt %d/%d: %s", attempt, self._max_retries, e)
                if attempt < self._max_retries:
                    time.sleep(self._backoff * attempt)
                    continue
                # exhausted retries -> return failure with exception info
                logger.warning("[Gotify] exhausted retries; last error: %s", e)
                return {"ok": False, "status_code": None, "error": str(e), "payload": payload}
            except RequestException as e:
                # other requests exceptions (may include response attr)
                resp = getattr(e, "response", None)
                status = getattr(resp, "status_code", None)
                text = getattr(resp, "text", None)
                logger.warning("[Gotify] request exception: status=%s text_preview=%s exc=%s", status, (text or "")[:300], e)
                return {"ok": False, "status_code": status, "error": str(e), "response_text_preview": (text or "")[:300], "payload": payload}
            except Exception as e:
                # unexpected
                logger.exception("[Gotify] unexpected error sending notification")
                return {"ok": False, "error": str(e), "payload": payload}

        # fallback if loop exits unexpectedly
        if last_exc:
            return {"ok": False, "status_code": None, "error": str(last_exc), "payload": payload}
        return {"ok": False, "error": "unknown", "payload": payload}


_default_gotify = GotifyAdapter()


def notify_gotify(header: str, lines: Optional[List[str]] = None) -> dict:
    return _default_gotify.send(header, lines)
