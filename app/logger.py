# app/logger.py
import logging
import os
from logging.handlers import RotatingFileHandler
from typing import Optional

# importe les valeurs statiques depuis ton app/config (qui lit configlocal.cfg)
from .config import LOG_FILE, LOG_LEVEL, LOG_MAX_MB, LOG_BACKUPS, WERK_LEVEL

DEFAULT_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"

def _make_stream_handler(level: int):
    sh = logging.StreamHandler()
    sh.setLevel(level)
    sh.setFormatter(logging.Formatter(DEFAULT_FORMAT))
    return sh

def _make_file_handler(path: str, level: int, max_bytes: int, backups: int):
    # s'assure que le dossier existe
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fh = RotatingFileHandler(path, maxBytes=max_bytes, backupCount=backups, encoding="utf-8")
    fh.setLevel(level)
    fh.setFormatter(logging.Formatter(DEFAULT_FORMAT))
    return fh

def init_logging(app=None) -> logging.Logger:
    """
    Initialise le logging global et (si fourni) attache les mêmes handlers à app.logger.

    - app: instance Flask optionnelle. Si fournie, app.logger utilisera les handlers.
    - Retourne un logger racine pour ton application ("webhook-cleaner").
    """

    # Normalise le niveau
    level_name = (LOG_LEVEL or "INFO").upper()
    root_level = getattr(logging, level_name, logging.INFO)

    # Logger principal de l'application
    logger = logging.getLogger("webhook-cleaner")
    logger.setLevel(root_level)
    logger.propagate = False  # on gère explicitement les handlers

    # Evite d'ajouter plusieurs fois les mêmes handlers
    if not logger.handlers:
        # Toujours ajouter un StreamHandler pour voir les logs en console (utile dev / docker)
        logger.addHandler(_make_stream_handler(root_level))

        # Handler sur fichier si configuré
        if LOG_FILE:
            try:
                file_handler = _make_file_handler(LOG_FILE, root_level, LOG_MAX_MB * 1024 * 1024, LOG_BACKUPS)
                logger.addHandler(file_handler)
                logger.info(f"File logging enabled → {LOG_FILE}")
            except Exception as e:
                # Ne crashe pas si dossier/permission pose pb
                logger.warning(f"File logging disabled: {e}; stdout only.")

    # Configure niveau werkzeug (flask) séparément : il logge sous 'werkzeug'
    werk_level_name = (WERK_LEVEL or "WARNING").upper()
    werk_level = getattr(logging, werk_level_name, logging.WARNING)
    logging.getLogger("werkzeug").setLevel(werk_level)

    # Si on a une app Flask, attache les mêmes handlers à app.logger
    if app is not None:
        # On attache uniquement si app.logger n'a pas de handlers identiques
        flask_logger = app.logger
        flask_logger.setLevel(root_level)
        # Eviter duplicate : supprime handlers qui auraient le même type que ceux de 'logger'
        existing_types = {type(h) for h in flask_logger.handlers}
        for h in logger.handlers:
            if type(h) not in existing_types:
                flask_logger.addHandler(h)
        # Désactiver propagation pour éviter duplications via root logger
        flask_logger.propagate = False

    return logger
