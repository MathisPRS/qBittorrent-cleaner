# app/extensions.py
import time
from redis import Redis
from celery import Celery
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate

from .config import REDIS_URL, CELERY_BROKER_URL, CELERY_RESULT_BACKEND

db = SQLAlchemy()
migrate = Migrate()

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
    # init only Flask extensions here (no Celery config here)
    db.init_app(app)
    migrate.init_app(app, db)

    try:
        r = get_redis()
        set_ok = r.set(RECONCILE_GUARD_KEY, str(int(time.time())), nx=True, ex=RECONCILE_GUARD_TTL)
        if set_ok:
            # do nothing here: reconcile should be scheduled explicitly by a process that wants it
            pass
    except Exception:
        app.logger.exception("init_extensions: failed to set reconcile guard")

def make_celery(app):
    celery.conf.broker_url = app.config.get("CELERY_BROKER_URL", CELERY_BROKER_URL)
    celery.conf.result_backend = app.config.get("CELERY_RESULT_BACKEND", CELERY_RESULT_BACKEND)

    # UTC/timezone
    celery.conf.enable_utc = True
    celery.conf.timezone = "UTC"

    celery.conf.update(app.config)

    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)
    celery.Task = ContextTask

    celery.conf.imports = ("app.tasks.deferred_tasks")
    return celery