# app/tasks/deferred_tasks.py
import time
from datetime import datetime
from typing import List
from flask import current_app
from app.extensions import celery, get_redis
from app.repositories.deferred_deletions_repo import DeferredDeletionsRepo
from app.services.deferred_deletion_services import DeferredDeletionService  # ton service existant

r = get_redis()
deferred_repo = DeferredDeletionsRepo()
service = DeferredDeletionService()  # adapte si ton constructeur attend args

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
        # 1) verify deferred row still exists and is due
        row = deferred_repo.get_by_hash(torrent_hash)
        if not row:
            current_app.logger.info("process_deferred_deletion: no deferred row for %s -> skip", torrent_hash)
            return

        # ensure it's due (defensive)
        now_ts = int(time.time())
        try:
            due_ts = int(row.can_be_deleted_at.timestamp())
        except Exception:
            due_ts = now_ts

        if due_ts > now_ts:
            # not yet due: reschedule
            process_deferred_deletion.apply_async(args=(torrent_hash,), eta=row.can_be_deleted_at)
            current_app.logger.info("process_deferred_deletion: %s not due yet -> rescheduled", torrent_hash)
            return

        # 2) call your existing service to delete this hash (it expects list)
        try:
            result = service.perform_deletion_deferred([torrent_hash], notify=True)
        except Exception:
            current_app.logger.exception("process_deferred_deletion: perform_deletion_deferred failed for %s", torrent_hash)
            # retry with backoff
            raise self.retry(countdown=60)

        # 3) assume perform_deletion_deferred removed deferred rows for deleted/absent hashes
        current_app.logger.info("process_deferred_deletion: finished for %s -> result=%s", torrent_hash, result)

    finally:
        release_lock(lock_key)


@celery.task(name="deferred.reconcile_db_to_celery")
def reconcile_db_to_celery(batch_size: int = 500):
    """
    Read deferred_table and ensure each row has a Celery task scheduled.
    If row.can_be_deleted_at <= now -> enqueue immediate process task.
    If row.can_be_deleted_at in future -> schedule apply_async(eta=...).
    This function is safe / idempotent.
    """
    current_app.logger.info("reconcile_db_to_celery: starting reconciliation")
    offset = 0
    now_ts = int(time.time())
    while True:
        rows = deferred_repo.list_batch(limit=batch_size, offset=offset)
        if not rows:
            break
        for r in rows:
            try:
                # defensive: ensure torrent_hash and can_be_deleted_at exist
                if not getattr(r, "torrent_hash", None):
                    continue
                ts = int(r.can_be_deleted_at.timestamp()) if r.can_be_deleted_at else now_ts
                if ts <= now_ts:
                    # immediate
                    process_deferred_deletion.apply_async(args=(r.torrent_hash,))
                    current_app.logger.debug("reconcile: enqueued immediate for %s", r.torrent_hash)
                else:
                    # schedule in future
                    # store task_id if repo model supports it (repo handles storing)
                    task = process_deferred_deletion.apply_async(args=(r.torrent_hash,), eta=r.can_be_deleted_at)
                    try:
                        # prefer repo method update celery_task_id if present
                        deferred_repo.set_task_id_for_hash(r.torrent_hash, task.id)
                    except Exception:
                        current_app.logger.debug("reconcile: can't store task id for %s", r.torrent_hash)
            except Exception:
                current_app.logger.exception("reconcile_db_to_celery: failed for row %s", getattr(r, "torrent_hash", "(unknown)"))
        offset += batch_size
    current_app.logger.info("reconcile_db_to_celery: finished")