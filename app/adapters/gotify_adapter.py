import logging, requests
from ..config import GOTIFY_ENABLED, GOTIFY_URL, GOTIFY_TOKEN, GOTIFY_PRIO, GOTIFY_TITLE, DRY_RUN

log = logging.getLogger("webhook-cleaner")

def notify_gotify(header: str, lines: list[str]):
    if not GOTIFY_ENABLED or not GOTIFY_URL or not GOTIFY_TOKEN:
        return
    body = "\n".join(f"- {x}" for x in lines[:20]) if lines else ""
    msg = f"{header}\n{body}"
    if DRY_RUN:
        msg = "[DRY_RUN] " + msg
    try:
        r = requests.post(f"{GOTIFY_URL}/message",
                          params={"token": GOTIFY_TOKEN},
                          json={"title": GOTIFY_TITLE, "message": msg, "priority": GOTIFY_PRIO},
                          timeout=10)
        r.raise_for_status()
        log.info("Notification Gotify envoyée.")
    except Exception as e:
        log.warning(f"Echec envoi Gotify: {e}")