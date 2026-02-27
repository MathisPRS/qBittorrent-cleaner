# app/logger.py
import logging
import os
from logging.handlers import RotatingFileHandler
from typing import Optional

# importe les valeurs statiques depuis ton app/config (qui lit configlocal.cfg)
from .config import LOG_FILE, LOG_LEVEL, LOG_MAX_MB, LOG_BACKUPS, WERK_LEVEL

DEFAULT_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"

def _make_stream_handler(level: int) -> logging.Handler:
    sh = logging.StreamHandler()
    sh.setLevel(level)
    sh.setFormatter(logging.Formatter(DEFAULT_FORMAT))
    return sh

def _make_file_handler(path: str, level: int, max_bytes: int, backups: int) -> logging.Handler:
    # s'assure que le dossier existe
    folder = os.path.dirname(path) or "."
    os.makedirs(folder, exist_ok=True)
    fh = RotatingFileHandler(path, maxBytes=max_bytes, backupCount=backups, encoding="utf-8")
    fh.setLevel(level)
    fh.setFormatter(logging.Formatter(DEFAULT_FORMAT))
    return fh

# Logger racine de l'application (nom configurable si besoin)
_ROOT_LOGGER_NAME = "webhook-cleaner"
_initialized = False

def init_logging(app=None) -> logging.Logger:
    
    global _initialized

    level_name = (LOG_LEVEL or "INFO").upper()
    root_level = getattr(logging, level_name, logging.INFO)

    logger = logging.getLogger(_ROOT_LOGGER_NAME)
    logger.setLevel(root_level)
    logger.propagate = False  # on gère explicitement les handlers

    if not _initialized:
        # Evite d'ajouter plusieurs fois les mêmes handlers
        # Toujours ajouter un StreamHandler pour voir les logs en console (utile dev / docker)
        logger.addHandler(_make_stream_handler(root_level))

        # Handler sur fichier si configuré
        if LOG_FILE:
            try:
                max_mb = int(LOG_MAX_MB or 10)
                backups = int(LOG_BACKUPS or 5)
                file_handler = _make_file_handler(LOG_FILE, root_level, max_mb * 1024 * 1024, backups)
                logger.addHandler(file_handler)
                logger.info(f"File logging enabled → {LOG_FILE}")
            except Exception as e:
                # Ne crashe pas si dossier/permission pose pb
                logger.warning(f"File logging disabled: {e}; stdout only.")

        _initialized = True

    # Configure niveau werkzeug (flask) séparément : il logge sous 'werkzeug'
    werk_level_name = (WERK_LEVEL or "WARNING").upper()
    werk_level = getattr(logging, werk_level_name, logging.WARNING)
    logging.getLogger("werkzeug").setLevel(werk_level)

    # Si on a une app Flask, attache les mêmes handlers à app.logger
    if app is not None:
        flask_logger = app.logger
        flask_logger.setLevel(root_level)

        # Eviter duplicate : ajoute uniquement handlers qui n'existent pas encore
        existing_types = {type(h) for h in flask_logger.handlers}
        for h in logger.handlers:
            if type(h) not in existing_types:
                flask_logger.addHandler(h)
        flask_logger.propagate = False

    return logger

def get_logger(name: Optional[str] = None, app=None) -> logging.Logger:
    
    # S'assurer que l'initialisation globale est faite
    root = init_logging(app=app)
    if not name:
        name = _ROOT_LOGGER_NAME
    log = logging.getLogger(name)
    log.setLevel(root.level)

    # Attacher handlers du root logger si nécessaire (évite duplications)
    root_handler_types = {type(h) for h in root.handlers}
    existing_types = {type(h) for h in log.handlers}
    for h in root.handlers:
        if type(h) not in existing_types:
            log.addHandler(h)

    log.propagate = False
    return log
