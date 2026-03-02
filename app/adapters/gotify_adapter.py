# adapters/gotify_adapter.py
from typing import List, Optional
import requests
import mimetypes
from urllib.parse import urlsplit, unquote
from requests.exceptions import RequestException
from app.logger import get_logger
from .. import config as app_config

logger = get_logger(__name__)


class GotifyAdapter:
    def __init__(self):
        self.enabled = bool(getattr(app_config, "GOTIFY_ENABLED", False))
        self.base_url = (getattr(app_config, "GOTIFY_URL", "") or "").rstrip("/")
        self.token = getattr(app_config, "GOTIFY_TOKEN", "")
        self.priority = int(getattr(app_config, "GOTIFY_PRIO", 5))
        self.verify_ssl = bool(getattr(app_config, "VERIFY_SSL", True))
        self.default_title = getattr(app_config, "GOTIFY_TITLE", "Cleaner qBittorrent")
        self.session = requests.Session()
        self._max_image_bytes = int(getattr(app_config, "GOTIFY_MAX_IMAGE_BYTES", 8 * 1024 * 1024))
        self._user_agent = getattr(app_config, "GOTIFY_USER_AGENT", "gotify-client/1.0")


    def _infer_filename(self, url: str, content_type: Optional[str]) -> str:
        try:
            path = unquote(urlsplit(url).path or "")
            candidate = path.rsplit("/", 1)[-1]
            if candidate and "." in candidate:
                return candidate
        except Exception:
            pass
        if content_type and "/" in content_type:
            ext = mimetypes.guess_extension(content_type.split(";")[0].strip())
            if ext:
                return f"image{ext}"
        return "image.jpg"
    

    def _post_json(self, title: str, message: str) -> dict:
        post_url = f"{self.base_url}/message"
        payload = {"title": title or self.default_title, "message": message, "priority": self.priority}
        try:
            r = self.session.post(post_url, params={"token": self.token}, json=payload, timeout=8, verify=self.verify_ssl)
            r.raise_for_status()
            logger.info("[Gotify] sent JSON: title=%s status=%s", payload["title"], r.status_code)
            return {"ok": True, "status_code": r.status_code}
        except RequestException as exc:
            logger.warning("[Gotify] JSON send failed: %s", exc)
            return {"ok": False, "error": str(exc)}
        

    def send(self, title: str, lines: Optional[List[str]] = None, image_url: Optional[str] = None) -> dict:
        if not (self.enabled and self.base_url and self.token):
            logger.debug("[Gotify] disabled or not configured; skipping")
            return {"ok": False, "error": "disabled_or_not_configured"}

        post_url = f"{self.base_url}/message"
        message_text = "\n".join([l for l in (lines or []) if l and l.strip()]).strip()
        title = title or self.default_title

        # no image: quick path
        if not image_url:
            return self._post_json(title, message_text)

        # try to fetch image (single attempt)
        try:
            headers = {"User-Agent": self._user_agent, "Accept": "image/*,*/*;q=0.8"}
            r = self.session.get(image_url, headers=headers, stream=True, timeout=8, verify=self.verify_ssl)
            r.raise_for_status()

            content_type = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            content_length = r.headers.get("Content-Length")
            if not content_type.startswith("image/"):
                logger.warning("[Gotify] fetched resource not image (Content-Type=%s) -> fallback to URL", content_type)
                return self._post_json(title, (message_text + "\nImage: " + image_url).strip())

            # check length header quickly
            if content_length:
                try:
                    if int(content_length) > self._max_image_bytes:
                        logger.warning("[Gotify] image too large by header (%s) -> fallback to URL", content_length)
                        return self._post_json(title, (message_text + "\nImage: " + image_url).strip())
                except ValueError:
                    pass

            img_bytes = r.content
            if len(img_bytes) > self._max_image_bytes:
                logger.warning("[Gotify] image bytes too large (%d) -> fallback to URL", len(img_bytes))
                return self._post_json(title, (message_text + "\nImage: " + image_url).strip())

            filename = self._infer_filename(image_url, content_type)
            files = {"attachment": (filename, img_bytes, content_type)}
            data = {"title": title, "message": message_text, "priority": str(self.priority)}

            # single multipart attempt
            try:
                r2 = self.session.post(post_url, params={"token": self.token}, data=data, files=files, timeout=15, verify=self.verify_ssl)
                r2.raise_for_status()
                logger.info("[Gotify] sent with attachment: title=%s status=%s", title, r2.status_code)
                return {"ok": True, "status_code": r2.status_code}
            except RequestException as exc:
                logger.warning("[Gotify] multipart upload failed: %s -> fallback to JSON with URL", exc)
                return self._post_json(title, (message_text + "\nImage: " + image_url).strip())

        except RequestException as exc:
            logger.warning("[Gotify] failed to fetch image '%s': %s -> sending URL instead", image_url, exc)
            return self._post_json(title, (message_text + "\nImage: " + image_url).strip())


# module-level default + helper (keeps existing notify_gotify contract)
_default_gotify = GotifyAdapter()


def notify_gotify(title: str, lines: Optional[List[str]] = None, image_url: Optional[str] = None) -> dict:
    return _default_gotify.send(title, lines, image_url=image_url)