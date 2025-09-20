import os, configparser

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.getenv("CONFIG_FILE", os.path.join(os.path.dirname(BASE_DIR), "configlocal.cfg"))

cfg = configparser.ConfigParser()
if not cfg.read(CONFIG_FILE):
    raise SystemExit(f"Config file not found or unreadable: {CONFIG_FILE}")

def getbool(section, key, default=False):
    try: return cfg.getboolean(section, key)
    except Exception: return default

# General
LOG_LEVEL      = cfg.get("general", "LOG_LEVEL").upper()
DRY_RUN        = getbool("general", "DRY_RUN",)
ONLY_UPGRADES  = getbool("general", "ONLY_UPGRADES")

# Server
SERVER_HOST    = cfg.get("server", "HOST")
SERVER_PORT    = int(cfg.get("server", "PORT"))

# Logging
LOG_FILE       = cfg.get("logging", "LOG_FILE")
LOG_MAX_MB     = int(cfg.get("logging", "MAX_MB"))
LOG_BACKUPS    = int(cfg.get("logging", "BACKUPS"))
WERK_LEVEL     = cfg.get("logging", "WERKZEUG_LEVEL").upper()

# External services
SONARR_URL = cfg.get("sonarr", "URL").rstrip("/")
SONARR_KEY = cfg.get("sonarr", "API_KEY")

RADARR_URL = cfg.get("radarr", "URL").rstrip("/")
RADARR_KEY = cfg.get("radarr", "API_KEY")

QBIT_HOST  = cfg.get("qbittorrent", "HOST" ).rstrip("/")
QBIT_USER  = cfg.get("qbittorrent", "USER" )
QBIT_PASS  = cfg.get("qbittorrent", "PASS")

# Gotify
GOTIFY_ENABLED = getbool("gotify", "ENABLED")
GOTIFY_URL     = cfg.get("gotify", "URL").rstrip("/")
GOTIFY_TOKEN   = cfg.get("gotify", "TOKEN")
GOTIFY_PRIO    = int(cfg.get("gotify", "PRIORITY"))
GOTIFY_TITLE   = cfg.get("gotify", "TITLE")

# HTTP tunables
REQ_TIMEOUT      = 12
MAX_RETRIES      = 3
HIST_PAGE_SIZE   = 1000
HIST_MAX_MISSES  = 3
HIST_MAX_PAGES   = 20
