# adapters/gotify_adapter.py
from typing import List, Optional
import time
import json
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
        self.session = requests.Session()
        if not self.verify_ssl:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        self._max_retries = 2
        self._backoff = 0.3

    def send(self, header: str, lines: Optional[List[str]] = None) -> dict:
        if not self.enabled or not self.url or not self.token:
            logger.debug("[Gotify] disabled or not configured; skipping")
            return {"ok": False, "error": "disabled_or_not_configured"}

        # Build full message (join lines with newline). Keep trimming empty lines.
        message_lines = [str(l).strip() for l in (lines or []) if l and str(l).strip()]
        body_msg = "\n".join(message_lines)

        payload = {"title": header or self.title_default, "message": body_msg, "priority": self.priority}
        url = f"{self.url}/message"

        # dry-run
        if self.dry_run:
            logger.info("[Gotify] [DRY_RUN] title=%s\nmessage=%s", payload["title"], payload["message"])
            return {"ok": True, "status_code": None, "dry_run": True, "payload": payload}

        last_exc = None
        for attempt in range(1, self._max_retries + 1):
            try:
                logger.debug("[Gotify] POST %s params=***** payload_preview=%s (attempt %d)", url,
                             {"title": payload["title"], "message_preview": (payload["message"] or "")[:400]}, attempt)
                r = self.session.post(url, params={"token": self.token}, json=payload, timeout=8, verify=self.verify_ssl)

                status = getattr(r, "status_code", None)
                text_preview = (r.text or "")[:1000]

                if status and 200 <= status < 300:
                    logger.info("[Gotify] sent: title=%s status=%s", payload["title"], status)
                    return {"ok": True, "status_code": status, "payload": payload}
                else:
                    # non 2xx -> no retry (server returned error)
                    logger.warning("[Gotify] send returned non-2xx status=%s text_preview=%s", status, text_preview)
                    return {"ok": False, "status_code": status, "error": f"HTTP {status}", "response_text_preview": text_preview, "payload": payload}

            except (ConnectionError, Timeout) as e:
                last_exc = e
                logger.warning("[Gotify] network error on attempt %d/%d: %s", attempt, self._max_retries, e)
                if attempt < self._max_retries:
                    time.sleep(self._backoff * attempt)
                    continue
                logger.warning("[Gotify] exhausted retries; last error: %s", e)
                return {"ok": False, "status_code": None, "error": str(e), "payload": payload}
            except RequestException as e:
                resp = getattr(e, "response", None)
                status = getattr(resp, "status_code", None)
                text = getattr(resp, "text", None)
                logger.warning("[Gotify] request exception: status=%s text_preview=%s exc=%s", status, (text or "")[:300], e)
                return {"ok": False, "status_code": status, "error": str(e), "response_text_preview": (text or "")[:300], "payload": payload}
            except Exception as e:
                logger.exception("[Gotify] unexpected error sending notification")
                return {"ok": False, "error": str(e), "payload": payload}

        # fallback
        if last_exc:
            return {"ok": False, "status_code": None, "error": str(last_exc), "payload": payload}
        return {"ok": False, "error": "unknown", "payload": payload}

_default_gotify = GotifyAdapter()

def notify_gotify(header: str, lines: Optional[List[str]] = None) -> dict:
    return _default_gotify.send(header, lines)
