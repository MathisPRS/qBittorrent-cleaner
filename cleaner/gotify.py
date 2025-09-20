import requests, logging
from .config import GOTIFY_ENABLED, GOTIFY_URL, GOTIFY_TOKEN, GOTIFY_PRIO, GOTIFY_TITLE

log = logging.getLogger("webhook-cleaner")

def send_gotify(message: str, title: str | None = None, priority: int | None = None):
    if not GOTIFY_ENABLED or not GOTIFY_URL or not GOTIFY_TOKEN:
        log.debug("Gotify disabled or not configured; skipping notification.")
        return
    payload = {
        "title": title or GOTIFY_TITLE,
        "message": message,
        "priority": priority if priority is not None else GOTIFY_PRIO,
    }
    try:
        r = requests.post(f"{GOTIFY_URL}/message", params={"token": GOTIFY_TOKEN}, json=payload, timeout=8)
        r.raise_for_status()
        log.info("Notification Gotify envoyée.")
    except Exception as e:
        log.warning(f"Echec envoi Gotify: {e}")
