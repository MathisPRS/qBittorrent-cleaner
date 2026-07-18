# app/extensions.py
import time
import sqlite3
from redis import Redis
from celery import Celery
from celery.schedules import crontab
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from sqlalchemy import event
from sqlalchemy.engine import Engine

from .config import REDIS_URL, CELERY_BROKER_URL, CELERY_RESULT_BACKEND, AUDIT_ENABLED

db = SQLAlchemy()
migrate = Migrate()


@event.listens_for(Engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record):
    # SQLite uniquement : WAL + busy_timeout pour eviter les "database is locked"
    # (API Flask + worker Celery + beat accedent au meme fichier app.db).
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA synchronous=NORMAL")
        finally:
            cursor.close()

# create an unconfigured Celery instance (we'll configure it with make_celery)
celery = Celery(__name__)

# Redis singleton
_REDIS = None
RECONCILE_GUARD_KEY = "deferred:reconcile_scheduled"
RECONCILE_GUARD_TTL = 60 * 5  # 5 minutes

def get_redis():
    global _REDIS
    if _REDIS is None:
        try:
            _REDIS = Redis.from_url(REDIS_URL) if REDIS_URL else Redis(host="redis", port=6379)
        except Exception:
            _REDIS = Redis(host="redis", port=6379)
    return _REDIS

def init_extensions(app):
    db.init_app(app)
    migrate.init_app(app, db)

def make_celery(app):
    celery.conf.broker_url = app.config.get("CELERY_BROKER_URL", CELERY_BROKER_URL)
    celery.conf.result_backend = app.config.get("CELERY_RESULT_BACKEND", CELERY_RESULT_BACKEND)

    # UTC/timezone
    celery.conf.enable_utc = True
    celery.conf.timezone = "UTC"

    celery.conf.update(app.config)

    # Redis broker : le visibility_timeout DOIT dépasser le plus long ETA de tâche
    # différée (DEFFERED_DELETION_DELTA = 73h), sinon Redis considère la tâche "perdue"
    # et la redélivre en boucle toutes les heures jusqu'à son ETA. 7 jours = marge sûre.
    celery.conf.broker_transport_options = {"visibility_timeout": 7 * 24 * 3600}

    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)
    celery.Task = ContextTask

    celery.conf.imports = ["app.tasks.deferred_tasks", "app.tasks.detect_unpublish_torrents"]

    if AUDIT_ENABLED:
        celery.conf.beat_schedule = {
            "daily-audit-sync-unknown-torrents": {
                "task": "audit.sync_unknown_torrents",
                "schedule": crontab(hour=20, minute=0),
            },
        }
    else:
        celery.conf.beat_schedule = {}

    return celery