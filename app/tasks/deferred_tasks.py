# app/tasks/deferred_tasks.py
import time
from datetime import datetime, timezone
from typing import Optional
from flask import current_app
from app.extensions import celery, get_redis
from app.repositories.deferred_deletions_repo import DeferredDeletionsRepo
from app.services.deferred_deletions_services import DeferredDeletionService
from celery.result import AsyncResult

r = get_redis()
deferred_repo = DeferredDeletionsRepo()
deferred_service = DeferredDeletionService(app=current_app._get_current_object())
LOCK_PREFIX = "deferred:lock:"

def acquire_lock(lock_key: str, ttl: int = 60) -> bool:
    try:
        return bool(r.set(lock_key, "1", nx=True, ex=ttl))
    except Exception:
        current_app.logger.exception("acquire_lock failed for %s", lock_key)
        return False

def release_lock(lock_key: str) -> None:
    try:
        r.delete(lock_key)
    except Exception:
        current_app.logger.exception("release_lock failed for %s", lock_key)

@celery.task(name="deferred.process_deferred_deletion", bind=True, max_retries=3)
def process_deferred_deletion(self, torrent_hash: str):
    lock_key = LOCK_PREFIX + torrent_hash
    if not acquire_lock(lock_key, ttl=120):
        current_app.logger.info("process_deferred_deletion: lock exists for %s -> skipping", torrent_hash)
        return

    try:
        row = deferred_repo.get_by_hash(torrent_hash)
        if not row:
            current_app.logger.info("process_deferred_deletion: no deferred row for %s -> skip", torrent_hash)
            return
        now_ts = int(time.time())

        try:
            due_ts = int(row.can_be_deleted_at.timestamp()) if row.can_be_deleted_at else now_ts
        except Exception:
            due_ts = now_ts

        if due_ts > now_ts:
            # reschedule if executed too early (defensive)
            process_deferred_deletion.apply_async(args=(torrent_hash,), eta=row.can_be_deleted_at)
            current_app.logger.info("process_deferred_deletion: %s not due -> rescheduled", torrent_hash)
            return

        try:
            result = deferred_service.perform_deletion_deferred([torrent_hash], notify=True)
            current_app.logger.info("process_deferred_deletion: finished for %s result=%s", torrent_hash, result)
        except Exception:
            current_app.logger.exception("process_deferred_deletion: perform_deletion_deferred failed for %s", torrent_hash)
            raise self.retry(countdown=60)

    finally:
        release_lock(lock_key)


@celery.task(name="deferred.reconcile_db_to_celery")
def reconcile_db_to_celery(batch_size: int = 500):
    current_app.logger.info("reconcile_db_to_celery: starting")
    offset = 0
    now_ts = _now_ts()

    while True:
        rows = deferred_repo.list_batch(limit=batch_size, offset=offset)
        if not rows:
            break

        for r in rows:
            try:
                torrent_hash = getattr(r, "torrent_hash", None)
                if not torrent_hash:
                    continue

                can_be = getattr(r, "can_be_deleted_at", None)
                ts = int(can_be.timestamp()) if can_be else now_ts

                if ts <= now_ts:
                    handle_row_immediate(r)
                else:
                    handle_row_future(r)

            except Exception:
                current_app.logger.exception("reconcile_db_to_celery: failed processing row %s", getattr(r, "torrent_hash", "(unknown)"))
        offset += batch_size

    current_app.logger.info("reconcile_db_to_celery: finished")

# -----------------------------
# Helpers pour reconcile
# -----------------------------
def _now_ts() -> int:
    return int(datetime.now(timezone.utc).timestamp())

def is_task_scheduled_on_workers(task_id: str) -> bool:
    """
    Returns True if found, False otherwise.
    """
    if not task_id:
        return False
    try:
        inspector = celery.control.inspect(timeout=1.0)
        for method in ("scheduled", "reserved", "active"):
            res = getattr(inspector, method)()
            if not res:
                continue
            for worker, entries in (res.items() if isinstance(res, dict) else []):
                for e in entries or []:
                    # scheduled entries tend to be dicts containing request -> id
                    if isinstance(e, dict):
                        rid = None
                        if "request" in e and isinstance(e["request"], dict):
                            rid = e["request"].get("id")
                        rid = rid or e.get("id")
                        if rid == task_id:
                            return True
                    else:
                        # fallback string matching
                        try:
                            if task_id in str(e):
                                return True
                        except Exception:
                            pass
        return False
    except Exception:
        current_app.logger.debug("is_task_scheduled_on_workers: inspector failed for %s", task_id, exc_info=True)
        # inspector failure -> be conservative (treat as not found)
        return False
    

def should_reschedule_task(existing_task_id: Optional[str]) -> bool:
    """
    Decide whether to reschedule a task whose id is existing_task_id.
    Returns True if we should schedule a new task.
    """
    if not existing_task_id:
        return True

    try:
        ar = AsyncResult(existing_task_id, app=celery)
        state = getattr(ar, "state", None)
        # finished states -> must reschedule
        if state in ("SUCCESS", "FAILURE", "REVOKED"):
            current_app.logger.info("should_reschedule_task: task %s state=%s -> reschedule", existing_task_id, state)
            return True

        # PENDING/RETRY ambiguous -> inspect workers
        if state in (None, "PENDING", "RETRY"):
            if not is_task_scheduled_on_workers(existing_task_id):
                current_app.logger.info("should_reschedule_task: inspector did not find %s -> reschedule", existing_task_id)
                return True
            # inspector found it -> keep
            return False

        # STARTED or other active states -> keep
        current_app.logger.debug("should_reschedule_task: task %s state=%s -> keep", existing_task_id, state)
        return False

    except Exception:
        current_app.logger.exception("should_reschedule_task: AsyncResult check failed for %s -> reschedule", existing_task_id)
        return True

def schedule_task(torrent_hash: str, eta: Optional[datetime]) -> Optional[AsyncResult]:
    """
    Schedule the deferred deletion task and return the AsyncResult (or None).
    Use apply_async on the callable so it's registered; if circular imports are an issue,
    replace this with celery.send_task(TASK_NAME, args=..., eta=...).
    """
    try:
        if eta:
            ar = process_deferred_deletion.apply_async(args=(torrent_hash,), eta=eta)
        else:
            ar = process_deferred_deletion.apply_async(args=(torrent_hash,))
        return ar
    except Exception:
        current_app.logger.exception("schedule_task: failed to schedule %s for eta=%s", torrent_hash, eta)
        return None

def persist_task_id(torrent_hash: str, task_id: Optional[str]) -> bool:
    if not task_id:
        return False
    try:
        return bool(deferred_repo.set_task_id_for_hash(torrent_hash, task_id))
    except Exception:
        current_app.logger.exception("persist_task_id: failed to persist task_id for %s", torrent_hash)
        return False

def handle_row_immediate(row) -> None:
    """
    For rows where can_be_deleted_at <= now: enqueue immediate execution and persist id if possible.
    """
    torrent_hash = getattr(row, "torrent_hash", None)
    if not torrent_hash:
        return
    current_app.logger.info("handle_row_immediate: enqueue immediate deletion for %s", torrent_hash)
    ar = schedule_task(torrent_hash, eta=None)
    task_id = getattr(ar, "id", None) if ar else None
    if task_id:
        if persist_task_id(torrent_hash, task_id):
            current_app.logger.debug("handle_row_immediate: persisted task_id %s for %s", task_id, torrent_hash)
        else:
            current_app.logger.debug("handle_row_immediate: could not persist task_id %s for %s", task_id, torrent_hash)

def handle_row_future(row) -> None:
    """
    For rows with future can_be_deleted_at: ensure there's a valid scheduled task.
    """
    torrent_hash = getattr(row, "torrent_hash", None)
    if not torrent_hash:
        return

    existing_task_id = getattr(row, "celery_task_id", None)
    can_be = getattr(row, "can_be_deleted_at", None)

    if not existing_task_id:
        current_app.logger.info("handle_row_future: no task_id for %s -> scheduling", torrent_hash)
        ar = schedule_task(torrent_hash, eta=can_be)
        task_id = getattr(ar, "id", None) if ar else None
        if task_id:
            persist_task_id(torrent_hash, task_id)
            current_app.logger.info("handle_row_future: scheduled %s at %s -> task_id=%s", torrent_hash, can_be, task_id)
        return

    # if there's an existing task_id, check if it's still valid
    if should_reschedule_task(existing_task_id):
        current_app.logger.info("handle_row_future: rescheduling %s (old task=%s)", torrent_hash, existing_task_id)
        ar = schedule_task(torrent_hash, eta=can_be)
        task_id = getattr(ar, "id", None) if ar else None
        if task_id:
            persist_task_id(torrent_hash, task_id)
            current_app.logger.info("handle_row_future: rescheduled %s at %s -> new task_id=%s", torrent_hash, can_be, task_id)
    else:
        current_app.logger.debug("handle_row_future: existing task %s for %s seems OK", existing_task_id, torrent_hash)

