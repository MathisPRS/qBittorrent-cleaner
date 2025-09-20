import logging, os
from logging.handlers import RotatingFileHandler
from .config import LOG_LEVEL, LOG_FILE, LOG_MAX_MB, LOG_BACKUPS, WERK_LEVEL

def init_logging():
    logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO),
                        format="%(asctime)s %(levelname)s: %(message)s")
    log = logging.getLogger("webhook-cleaner")
    if LOG_FILE:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        fh = RotatingFileHandler(
            LOG_FILE, maxBytes=LOG_MAX_MB*1024*1024, backupCount=LOG_BACKUPS, encoding="utf-8"
        )
        fh.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
        logging.getLogger().addHandler(fh)
    logging.getLogger("werkzeug").setLevel(getattr(logging, WERK_LEVEL, logging.WARNING))
    return log
