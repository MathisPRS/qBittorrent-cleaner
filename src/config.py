import os, configparser

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
CONFIG_FILE = os.getenv("CONFIG_FILE", os.path.join(ROOT_DIR, "configlocal.cfg"))

cfg = configparser.ConfigParser()
cfg.read(CONFIG_FILE)

def getbool(section, key, default=False):
    try: return cfg.getboolean(section, key, fallback=default)
    except Exception: return default

# Server
SERVER_HOST = cfg.get("server", "HOST", fallback="0.0.0.0")
SERVER_PORT = int(cfg.get("server", "PORT", fallback="8124"))

# Logging
LOG_FILE    = cfg.get("logging", "LOG_FILE", fallback="/app/logs/webhook-cleaner.log")
LOG_MAX_MB  = int(cfg.get("logging", "MAX_MB", fallback="20"))
LOG_BACKUPS = int(cfg.get("logging", "BACKUPS", fallback="7"))
WERK_LEVEL  = (cfg.get("logging", "WERKZEUG_LEVEL", fallback="WARNING") or "WARNING").upper()
LOG_LEVEL   = (cfg.get("general", "LOG_LEVEL", fallback="INFO") or "INFO").upper()

# qBittorrent
QBIT_HOST = cfg.get("qbittorrent", "HOST", fallback="http://qbittorrent:8080").rstrip("/")
QBIT_USER = cfg.get("qbittorrent", "USER", fallback="admin")
QBIT_PASS = cfg.get("qbittorrent", "PASS", fallback="adminadmin")

# Gotify
GOTIFY_ENABLED = getbool("gotify", "ENABLED", False)
GOTIFY_URL     = (cfg.get("gotify", "URL", fallback="")).rstrip("/")
GOTIFY_TOKEN   = cfg.get("gotify", "TOKEN", fallback="")
GOTIFY_PRIO    = int(cfg.get("gotify", "PRIORITY", fallback="5"))
GOTIFY_TITLE   = cfg.get("gotify", "TITLE", fallback="Cleaner qBittorrent")

# Catalog
CATALOG_FILE   = cfg.get("catalog", "FILE", fallback="/app/data/catalog.json")

# Sonarr (pour builder uniquement)
SONARR_URL = cfg.get("sonarr", "URL", fallback="http://sonarr:8989").rstrip("/")
SONARR_KEY = cfg.get("sonarr", "API_KEY", fallback="")

# Radarr (pour builder uniquement)
RADARR_URL = cfg.get("radarr", "URL", fallback="http://radarr:7878").rstrip("/")
RADARR_KEY = cfg.get("radarr", "API_KEY", fallback="")

# Misc
DRY_RUN = getbool("general", "DRY_RUN", False)
