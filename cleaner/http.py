import time, requests, logging
from .config import MAX_RETRIES, REQ_TIMEOUT

log = logging.getLogger("webhook-cleaner")

def json_get(url: str, headers=None, params=None):
    last_err = None
    for attempt in range(1, MAX_RETRIES+1):
        try:
            r = requests.get(url, headers=headers or {}, params=params or {}, timeout=REQ_TIMEOUT)
            if r.status_code in (429, 500, 502, 503, 504):
                last_err = RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
                sleep_s = min(2**attempt, 8)
                log.debug(f"retry {attempt}/{MAX_RETRIES} after {sleep_s}s → {url}")
                time.sleep(sleep_s); continue
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            sleep_s = min(2**attempt, 8)
            log.debug(f"retry {attempt}/{MAX_RETRIES} after {sleep_s}s → {url} ({e})")
            time.sleep(sleep_s)
    raise last_err
