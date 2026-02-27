# app/tasks/deferred_tasks.py
from celery import shared_task
from flask import current_app
from app.logger import get_logger

from ..services.deferred_deletion_services import DeferredDeletionService

logger = get_logger(__name__)

@shared_task(name="app.tasks.deferred_tasks.run_deferred_deletions", bind=False)
def run_deferred_deletions(batch_size: int = 50):
    
    app = current_app._get_current_object() if current_app else None
    if app is None:
        logger.error("run_deferred_deletions: no Flask current_app available in worker context")
        return {"error": "no_app_context"}

    svc = DeferredDeletionService(app=app)
    try:
        result = svc.process_ready_deferred_deletions(batch_size=batch_size)
        logger.info("run_deferred_deletions: result=%s", result)
        return result
    except Exception:
        logger.exception("run_deferred_deletions: unexpected error")
        return {"error": "exception"}