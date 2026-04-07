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
SERVER_PORT = int(cfg.get("server", "PORT", fallback="8129"))

# Logging
LOG_FILE    = cfg.get("logging", "LOG_FILE", fallback="/app/logs/webhook-cleaner.log")
LOG_MAX_MB  = int(cfg.get("logging", "MAX_MB", fallback="20"))
LOG_BACKUPS = int(cfg.get("logging", "BACKUPS", fallback="7"))
WERK_LEVEL  = (cfg.get("logging", "WERKZEUG_LEVEL", fallback="WARNING") or "WARNING").upper()
LOG_LEVEL   = (cfg.get("general", "LOG_LEVEL", fallback="INFO") or "INFO").upper()

# qBittorrent
QBIT_HOST = cfg.get("qbittorrent", "HOST", fallback="http://qbittorrrent:8080").rstrip("/")
QBIT_USER = cfg.get("qbittorrent", "USER" )
QBIT_PASS = cfg.get("qbittorrent", "PASS")
DEFFERED_DELETION_DELTA = cfg.getint("qbittorrent", "DEFFERED_DELETION_DELTA")


# Gotify
GOTIFY_ENABLED = getbool("gotify", "ENABLED", False)
GOTIFY_URL     = (cfg.get("gotify", "URL", fallback="")).rstrip("/")
GOTIFY_TOKEN   = cfg.get("gotify", "TOKEN", fallback="")
GOTIFY_PRIO    = int(cfg.get("gotify", "PRIORITY", fallback="5"))
GOTIFY_TITLE   = cfg.get("gotify", "TITLE", fallback="Cleaner qBittorrent")
VERIFY_SSL = getbool("gotify", "VERIFY_SSL", True)


# Sonarr (pour builder uniquement)
SONARR_URL = cfg.get("sonarr", "URL", fallback="http://sonarr:8989").rstrip("/")
SONARR_KEY = cfg.get("sonarr", "API_KEY", fallback="")

# Radarr (pour builder uniquement)
RADARR_URL = cfg.get("radarr", "URL", fallback="http://radarr:7878").rstrip("/")
RADARR_KEY = cfg.get("radarr", "API_KEY", fallback="")

# DATABASE: priorité env DATABASE_URL, sinon sqlite file in data/
DEFAULT_SQLITE = "sqlite:///" + os.path.join(ROOT_DIR, "data", "app.db")
DATABASE_URL = os.getenv("DATABASE_URL", cfg.get("database", "URL", fallback=DEFAULT_SQLITE))

# Flask-SQLAlchemy settings
SQLALCHEMY_DATABASE_URI = DATABASE_URL
SQLALCHEMY_TRACK_MODIFICATIONS = False
SQLALCHEMY_ECHO = getbool("database", "ECHO", False)

#REDIS
REDIS_URL = cfg.get("redis", "URL")
CELERY_BROKER_URL = cfg.get("redis", "CELERY_BROKER_URL")
CELERY_RESULT_BACKEND = cfg.get("redis", "CELERY_RESULT_BACKEND")

# Celery
AUDIT_ENABLED = getbool("celery", "AUDIT_ENABLED", False)

def configure_app(app, config_filename: str | None = None):
    app.config["SQLALCHEMY_DATABASE_URI"] = SQLALCHEMY_DATABASE_URI
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = SQLALCHEMY_TRACK_MODIFICATIONS
    app.config["SQLALCHEMY_ECHO"] = SQLALCHEMY_ECHO

    # logging / autres variables utiles
    app.config["SERVER_HOST"] = SERVER_HOST
    app.config["SERVER_PORT"] = SERVER_PORT

    # possibilité de charger override depuis un fichier .cfg passé
    if config_filename:
        app.config.from_pyfile(config_filename, silent=True)