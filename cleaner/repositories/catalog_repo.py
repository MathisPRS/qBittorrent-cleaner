import os, json, logging
from ..config import CATALOG_FILE

log = logging.getLogger("webhook-cleaner")

def _ensure_dir():
    d = os.path.dirname(CATALOG_FILE)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)

def load_catalog() -> dict:
    try:
        with open(CATALOG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"sonarr": {}, "radarr": {}, "meta": {}}

def save_catalog(cat: dict):
    try:
        _ensure_dir()
        tmp = CATALOG_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cat, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CATALOG_FILE)
    except Exception as e:
        log.warning(f"catalog save failed: {e}")
