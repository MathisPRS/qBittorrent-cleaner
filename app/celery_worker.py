# app/celery_worker.py
from app import create_app
from app.extensions import make_celery, celery, get_redis, RECONCILE_GUARD_KEY, RECONCILE_GUARD_TTL
from celery.signals import worker_ready
import logging

flask_app = create_app()

make_celery(flask_app)

logger = logging.getLogger("webhook-cleaner")

# 3) worker_ready handler to schedule reconcile ONCE (guarded by Redis NX)
@worker_ready.connect
def _on_worker_ready(sender, **kwargs):
    try:
        r = get_redis()
        # attempt to set guard key only if absent
        # returns True if the key was set (i.e. we are the first to schedule)
        set_ok = False
        try:
            set_ok = bool(r.set(RECONCILE_GUARD_KEY, "1", nx=True, ex=RECONCILE_GUARD_TTL))
        except Exception as e:
            # Redis unavailable or set failed; log and try to schedule anyway
            logger.exception("worker_ready: redis guard set failed, proceeding without guard; err=%s", e)

        if set_ok:
            # schedule reconcile shortly after worker is ready
            # use send_task by name to avoid circular imports
            try:
                # small delay to let worker stabilize
                celery.send_task("deferred.reconcile_db_to_celery", args=(), kwargs={"batch_size": 500})
                logger.info("worker_ready: scheduled deferred.reconcile_db_to_celery (guard set).")
            except Exception:
                logger.exception("worker_ready: failed to send_task reconcile_db_to_celery")
        else:
            # If guard wasn't set, either another process already scheduled it, or redis failed
            # still attempt to schedule if we couldn't set guard due to Redis error (optional)
            logger.info("worker_ready: reconcile guard not set (another process probably scheduled it), skipping.")
    except Exception:
        logger.exception("worker_ready: unexpected error")