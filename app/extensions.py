# app/extensions.py
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

    # Beat schedule: run every 2 hours on the hour (00:00, 02:00, 04:00, ...)
    celery.conf.beat_schedule = {
        "run-deferred-deletions-every-2h": {
            "task": "app.tasks.deferred_deletion_task.run_deferred_deletions",
            "schedule": crontab(minute=0, hour="*/2"),
            "args": (50,)
        }
    }