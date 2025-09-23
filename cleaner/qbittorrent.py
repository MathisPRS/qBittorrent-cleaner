import requests, time, logging
from .config import QBIT_HOST, QBIT_USER, QBIT_PASS, DRY_RUN

REQ_TIMEOUT = 12
log = logging.getLogger("webhook-cleaner")

def qb_login(sess: requests.Session):
    if DRY_RUN:
        log.debug("[DRY] qB login skipped"); return
    r = sess.post(f"{QBIT_HOST}/api/v2/auth/login",
                  data={"username": QBIT_USER, "password": QBIT_PASS},
                  timeout=REQ_TIMEOUT)
    if r.text.strip() != "Ok.":
        raise RuntimeError(f"qBittorrent login failed: {r.text}")

def qb_info_map(sess: requests.Session, hashes: list[str]) -> dict[str, dict]:
    if not hashes: return {}
    hs = "|".join(hashes)
    if DRY_RUN:
        return {h.lower(): {"name": f"torrent_{h[:8]}...", "hash": h} for h in hashes}
    r = sess.get(f"{QBIT_HOST}/api/v2/torrents/info",
                 params={"hashes": hs}, timeout=REQ_TIMEOUT)
    r.raise_for_status()
    out = {}
    for t in r.json():
        out[(t.get("hash") or "").lower()] = t
    return out

def qb_delete(sess: requests.Session, torrent_hash: str, delete_files=True, max_retry=2) -> tuple[bool, str]:
    info = qb_info_map(sess, [torrent_hash])
    name = (info.get((torrent_hash or "").lower(), {}) or {}).get("name", f"<{torrent_hash[:12]}>")
    log.info(f"Suppression qBittorrent: '{name}' ({torrent_hash}), deleteFiles={delete_files}")
    if DRY_RUN:
        log.info(f"[DRY] would delete '{name}'"); return True, name

    for attempt in range(max_retry + 1):
        r = sess.post(f"{QBIT_HOST}/api/v2/torrents/delete",
                      data={"hashes": torrent_hash,
                            "deleteFiles": "true" if delete_files else "false"},
                      timeout=REQ_TIMEOUT)
        if r.status_code not in (200, 415):
            log.warning(f"Delete returned {r.status_code}: {r.text[:200]}")
        time.sleep(0.4)
        still = qb_info_map(sess, [torrent_hash])
        if (torrent_hash or "").lower() not in still:
            return True, name
        log.warning(f"Tentative {attempt+1}/{max_retry}: toujours présent '{name}'")
    return False, name
