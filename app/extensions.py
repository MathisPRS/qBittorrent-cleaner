# app/extensions.py
import time
from redis import Redis
from celery import Celery
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate

from .config import (
    REDIS_URL,
    CELERY_BROKER_URL,
    CELERY_RESULT_BACKEND,
)

db = SQLAlchemy()
migrate = Migrate()
celery = Celery(__name__, broker=CELERY_BROKER_URL, backend=CELERY_RESULT_BACKEND)

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

    if "CELERY_BROKER_URL" in app.config:
        celery.conf.broker_url = app.config["CELERY_BROKER_URL"]
    if "CELERY_RESULT_BACKEND" in app.config:
        celery.conf.result_backend = app.config["CELERY_RESULT_BACKEND"]

    celery.autodiscover_tasks(["app.tasks"])

    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)
    celery.Task = ContextTask

    # --- ENQUEUE ONE-OFF reconciliation (guarded) ---
    try:
        r = get_redis()
        set_ok = r.set(RECONCILE_GUARD_KEY, str(int(time.time())), nx=True, ex=RECONCILE_GUARD_TTL)
        if set_ok:
            celery.send_task("deferred.reconcile_db_to_celery")
        else:
            app.logger.debug("Reconciliation already scheduled recently; skipping")
    except Exception:
        app.logger.exception("init_extensions: failed to schedule reconciliation")