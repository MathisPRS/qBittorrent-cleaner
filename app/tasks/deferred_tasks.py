# app/tasks/deferred_tasks.py
import time
from flask import current_app
from app.extensions import celery, get_redis
from app.repositories.deferred_deletions_repo import DeferredDeletionsRepo

# tasks import the service class (one direction)
from app.services.deferred_deletions_services import DeferredDeletionService

r = get_redis()
deferred_repo = DeferredDeletionsRepo()
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
        # instantiate the service in the worker context
        svc = DeferredDeletionService(app=current_app._get_current_object())

        # verify row exists
        row = deferred_repo.get_by_hash(torrent_hash)
        if not row:
            current_app.logger.info("process_deferred_deletion: no deferred row for %s -> skip", torrent_hash)
            return

        # ensure due
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

        # call business logic (list)
        try:
            result = svc.perform_deletion_deferred([torrent_hash], notify=True)
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
    now_ts = int(time.time())
    while True:
        rows = deferred_repo.list_batch(limit=batch_size, offset=offset)
        if not rows:
            break
        for r in rows:
            try:
                if not getattr(r, "torrent_hash", None):
                    continue
                ts = int(r.can_be_deleted_at.timestamp()) if r.can_be_deleted_at else now_ts
                if ts <= now_ts:
                    process_deferred_deletion.apply_async(args=(r.torrent_hash,))
                    current_app.logger.debug("reconcile: enqueued immediate for %s", r.torrent_hash)
                else:
                    task = process_deferred_deletion.apply_async(args=(r.torrent_hash,), eta=r.can_be_deleted_at)
                    try:
                        deferred_repo.set_task_id_for_hash(r.torrent_hash, task.id)
                    except Exception:
                        current_app.logger.debug("reconcile: cannot store task id for %s", r.torrent_hash)
            except Exception:
                current_app.logger.exception("reconcile_db_to_celery: failed for %s", getattr(r, "torrent_hash", "(unknown)"))
        offset += batch_size
    current_app.logger.info("reconcile_db_to_celery: finished")