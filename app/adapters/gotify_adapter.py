# adapters/gotify_adapter.py
from typing import List, Optional
import requests
from requests.exceptions import RequestException
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
        self.title_default = getattr(app_config, "GOTIFY_TITLE", "Cleaner qBittorrent")
        self.dry_run = getattr(app_config, "DRY_RUN", False)

        # simple session reuse for perf
        self.session = requests.Session()

    def send(self, header: str, lines: Optional[List[str]] = None) -> dict:
       
        if not self.enabled or not self.url or not self.token:
            logger.debug("[Gotify] disabled or not configured; skipping")
            return {"ok": False, "error": "disabled_or_not_configured"}

        # Use only first line as the single-line body
        body_line = ""
        if lines:
            for l in lines:
                if l and l.strip():
                    body_line = l.strip()
                    break

        if self.dry_run:
            logger.info("[Gotify] [DRY_RUN] title=%s body=%s", header, body_line)
            return {"ok": True, "status_code": None, "dry_run": True}

        payload = {"title": header or self.title_default, "message": body_line, "priority": self.priority}
        url = f"{self.url}/message"

        logger.debug("[Gotify] POST %s params=%s payload_preview=%s", url, {"token": "*****"}, {"title": payload["title"], "message": (payload["message"] or "")[:200]})
        try:
            r = self.session.post(url, params={"token": self.token}, json=payload, timeout=8)
            r.raise_for_status()
            logger.info("[Gotify] sent: title=%s status=%s", header, r.status_code)
            return {"ok": True, "status_code": r.status_code}
        except RequestException as e:
            resp = getattr(e, "response", None)
            status = getattr(resp, "status_code", None)
            text = getattr(resp, "text", None)
            logger.warning("[Gotify] send failed: status=%s text_preview=%s", status, (text or "")[:300])
            return {"ok": False, "status_code": status, "error": str(e)}
        except Exception as e:
            logger.exception("[Gotify] unexpected error sending notification")
            return {"ok": False, "error": str(e)}


_default_gotify = GotifyAdapter()


def notify_gotify(header: str, lines: Optional[List[str]] = None) -> dict:
    return _default_gotify.send(header, lines)
