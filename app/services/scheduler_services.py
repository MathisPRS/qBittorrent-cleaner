# app/services/scheduler_services.py
from typing import Optional
from datetime import datetime
from celery.result import AsyncResult
from app.extensions import celery
from app.logger import get_logger

logger = get_logger(__name__)

TASK_NAME = "deferred.process_deferred_deletion"

class SchedulerService:
    def __init__(self, app=None):
        self.app = app
        self.logger = get_logger(__name__, app=app)

    def schedule_deferred_for_hash(self, torrent_hash: str, can_be_deleted_at: datetime) -> Optional[str]:
        try:
            res = celery.send_task(TASK_NAME, args=(torrent_hash,), eta=can_be_deleted_at)
            return getattr(res, "id", None)
        except Exception:
            self.logger.exception("schedule_deferred_for_hash: failed to schedule %s", torrent_hash)
            return None

    def revoke_task(self, task_id: str) -> None:
        try:
            AsyncResult(task_id, app=celery).revoke(terminate=False)
        except Exception:
            self.logger.exception("revoke_task failed for %s", task_id)