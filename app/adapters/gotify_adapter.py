# adapters/gotify_adapter.py
from typing import List, Optional
import requests
import mimetypes
import logging
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
        self.verify_ssl = bool(getattr(app_config, "GOTIFY_VERIFY_SSL", True))
        self.default_title = getattr(app_config, "GOTIFY_TITLE", "Cleaner qBittorrent")
        self.session = requests.Session()

        # small constants
        self._max_image_bytes = int(getattr(app_config, "GOTIFY_MAX_IMAGE_BYTES", 8 * 1024 * 1024))
        self._user_agent = getattr(app_config, "GOTIFY_USER_AGENT", "gotify-client/1.0")

    def _infer_filename(self, url: str, content_type: str | None) -> str:
        # try to get name from URL path
        try:
            path = unquote(urlsplit(url).path or "")
            candidate = path.rsplit("/", 1)[-1]
            if candidate and "." in candidate:
                return candidate
        except Exception:
            pass
        # else try from content_type
        if content_type and "/" in content_type:
            ext = mimetypes.guess_extension(content_type.split(";")[0].strip())
            if ext:
                return f"image{ext}"
        # fallback
        return "image.jpg"

    def send(self, title: str, lines: Optional[List[str]] = None, image_url: Optional[str] = None) -> dict:
        """
        Send message to Gotify. If image_url provided, try to fetch and send as 'attachment'.
        Returns a dict with ok/status_code and helpful debug info.
        """
        if not (self.enabled and self.base_url and self.token):
            logger.debug("[Gotify] disabled or not configured; skipping")
            return {"ok": False, "error": "disabled_or_not_configured"}

        post_url = f"{self.base_url}/message"
        message_text = "\n".join([l for l in (lines or []) if l and l.strip()]).strip()
        payload = {"title": title or self.default_title, "message": message_text, "priority": self.priority}

        # If no image requested -> simple JSON POST
        if not image_url:
            try:
                r = self.session.post(post_url, params={"token": self.token}, json=payload, timeout=8, verify=self.verify_ssl)
                r.raise_for_status()
                logger.info("[Gotify] sent JSON: title=%s status=%s", payload["title"], r.status_code)
                return {"ok": True, "status_code": r.status_code}
            except RequestException as e:
                logger.warning("[Gotify] JSON send failed: %s", e)
                return {"ok": False, "error": str(e)}

        # Try to fetch image with a User-Agent (TMDB sometimes bloque les requêtes sans UA)
        try:
            headers = {"User-Agent": self._user_agent, "Accept": "image/*,*/*;q=0.8"}
            r_img = self.session.get(image_url, headers=headers, stream=True, timeout=10, verify=self.verify_ssl)
            r_img.raise_for_status()

            content_type = r_img.headers.get("Content-Type", "").split(";")[0].strip().lower()
            content_length = r_img.headers.get("Content-Length")
            logger.debug("[Gotify] fetched image url=%s status=%s type=%s len_header=%s",
                         image_url, r_img.status_code, content_type, content_length)

            # verify content-type looks like image/*
            if not content_type.startswith("image/"):
                # log and fallback to send URL in message (useful to debug)
                logger.warning("[Gotify] fetched resource is not image/* (Content-Type=%s). Fallback to sending URL.", content_type)
                payload["message"] = (message_text + "\nImage: " + image_url).strip()
                r = self.session.post(post_url, params={"token": self.token}, json=payload, timeout=8, verify=self.verify_ssl)
                r.raise_for_status()
                return {"ok": True, "status_code": r.status_code, "warning": "fetched_not_image_sent_url", "fetched_content_type": content_type}

            # size checks (header first, then actual bytes)
            if content_length:
                try:
                    if int(content_length) > self._max_image_bytes:
                        logger.warning("[Gotify] image too large (header %s) -> sending URL instead", content_length)
                        payload["message"] = (message_text + "\nImage: " + image_url).strip()
                        r = self.session.post(post_url, params={"token": self.token}, json=payload, timeout=8, verify=self.verify_ssl)
                        r.raise_for_status()
                        return {"ok": True, "status_code": r.status_code, "warning": "image_too_large_sent_url"}
                except ValueError:
                    pass

            img_bytes = r_img.content
            if len(img_bytes) > self._max_image_bytes:
                logger.warning("[Gotify] image bytes %d > max %d -> sending URL instead", len(img_bytes), self._max_image_bytes)
                payload["message"] = (message_text + "\nImage: " + image_url).strip()
                r = self.session.post(post_url, params={"token": self.token}, json=payload, timeout=8, verify=self.verify_ssl)
                r.raise_for_status()
                return {"ok": True, "status_code": r.status_code, "warning": "image_too_large_sent_url"}

            filename = self._infer_filename(image_url, content_type)

        except RequestException as e:
            logger.warning("[Gotify] failed to fetch image '%s': %s -> sending URL instead", image_url, e)
            payload["message"] = (message_text + "\nImage: " + image_url).strip()
            try:
                r = self.session.post(post_url, params={"token": self.token}, json=payload, timeout=8, verify=self.verify_ssl)
                r.raise_for_status()
                return {"ok": True, "status_code": r.status_code, "warning": "image_fetch_failed_sent_url"}
            except RequestException as e2:
                logger.warning("[Gotify] fallback JSON send also failed: %s", e2)
                return {"ok": False, "error": f"{e} ; fallback: {e2}"}

        # Now upload multipart/form-data with attachment
        files = {"attachment": (filename, img_bytes, content_type)}
        data = {"title": payload["title"], "message": payload["message"], "priority": str(payload["priority"])}

        try:
            r = self.session.post(post_url, params={"token": self.token}, data=data, files=files, timeout=20, verify=self.verify_ssl)
            status = getattr(r, "status_code", None)
            text_preview = (r.text or "")[:1000]
            logger.debug("[Gotify] multipart response status=%s preview=%s", status, text_preview)
            if status and 200 <= status < 300:
                logger.info("[Gotify] sent with attachment: title=%s status=%s", payload["title"], status)
                return {"ok": True, "status_code": status}
            else:
                logger.warning("[Gotify] attachment upload returned non-2xx status=%s -> fallback to URL", status)
                payload["message"] = (message_text + "\nImage: " + image_url).strip()
                r2 = self.session.post(post_url, params={"token": self.token}, json=payload, timeout=8, verify=self.verify_ssl)
                r2.raise_for_status()
                return {"ok": True, "status_code": r2.status_code, "warning": "attachment_failed_sent_url", "attach_response_preview": text_preview}
        except RequestException as e:
            logger.warning("[Gotify] multipart upload failed: %s", e)
            return {"ok": False, "error": str(e)}


_default_gotify = GotifyAdapter()


def notify_gotify(title: str, lines: Optional[List[str]] = None, image_url: Optional[str] = None) -> dict:
    return _default_gotify.send(title, lines, image_url=image_url)
