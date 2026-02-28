# app/extensions.py
import time
from redis import Redis
from celery import Celery
from celery.schedules import crontab
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate

from .config import (
    REDIS_URL,
    CELERY_BROKER_URL,
    CELERY_RESULT_BACKEND,
)

# Flask extensions
db = SQLAlchemy()
migrate = Migrate()
celery = Celery(__name__, broker=CELERY_BROKER_URL, backend=CELERY_RESULT_BACKEND)

# Redis singleton
_REDIS = None
REDIS_DB = 0

# Keys
RECONCILE_GUARD_KEY = "deferred:reconcile_scheduled"
RECONCILE_GUARD_TTL = 60 * 5  # 5 minutes

def get_redis():
    global _REDIS
    if _REDIS is None:
        try:
            # Prefer full URL if provided
            if REDIS_URL:
                _REDIS = Redis.from_url(REDIS_URL, db=REDIS_DB)
            else:
                _REDIS = Redis(host="redis", port=6379, db=REDIS_DB)
        except Exception:
            # Fallback
            _REDIS = Redis(host="redis", port=6379, db=REDIS_DB)
    return _REDIS

def init_extensions(app):
    db.init_app(app)
    migrate.init_app(app, db)

    if "CELERY_BROKER_URL" in app.config:
        celery.conf.broker_url = app.config["CELERY_BROKER_URL"]
    if "CELERY_RESULT_BACKEND" in app.config:
        celery.conf.result_backend = app.config["CELERY_RESULT_BACKEND"]

    # autodiscover tasks
    celery.autodiscover_tasks(["app.tasks"])

    # ensure tasks run inside Flask app context
    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)
    celery.Task = ContextTask

    # keep beat schedule if you still want a fallback:
    celery.conf.beat_schedule = {
        "run-deferred-deletions-every-2h": {
            "task": "app.tasks.deferred_deletion_task.run_deferred_deletions",
            "schedule": crontab(minute=0, hour="*/2"),
            "args": (50,)
        }
    }

    # Try to enqueue one reconciliation job (guarded by Redis SETNX)
    try:
        r = get_redis()
        set_ok = r.set(RECONCILE_GUARD_KEY, str(int(time.time())), nx=True, ex=RECONCILE_GUARD_TTL)
        if set_ok:
            # send a task to be executed by worker(s)
            celery.send_task("deferred.reconcile_db_to_celery")
        else:
            app.logger.debug("Reconciliation already scheduled recently; skipping enqueue")
    except Exception:
        app.logger.exception("init_extensions: failed to schedule reconciliation")