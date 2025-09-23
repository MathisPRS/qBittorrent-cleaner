import logging, time, requests
from ..config import QBIT_HOST, QBIT_USER, QBIT_PASS, DRY_RUN

log = logging.getLogger("webhook-cleaner")
REQ_TIMEOUT = 12

class QbitClient:
    def __init__(self):
        self.sess = requests.Session()

    def login(self):
        if DRY_RUN:
            log.debug("[DRY] qB login skipped"); return
        r = self.sess.post(f"{QBIT_HOST}/api/v2/auth/login",
                           data={"username": QBIT_USER, "password": QBIT_PASS},
                           timeout=REQ_TIMEOUT)
        if r.text.strip() != "Ok.":
            raise RuntimeError(f"qBittorrent login failed: {r.text}")

    def info_map(self, hashes: list[str]) -> dict[str, dict]:
        if not hashes: return {}
        hs = "|".join(hashes)
        if DRY_RUN:
            return {h.lower(): {"name": f"torrent_{h[:8]}...", "hash": h} for h in hashes}
        r = self.sess.get(f"{QBIT_HOST}/api/v2/torrents/info",
                          params={"hashes": hs}, timeout=REQ_TIMEOUT)
        r.raise_for_status()
        out = {}
        for t in r.json():
            out[(t.get("hash") or "").lower()] = t
        return out

    def delete(self, torrent_hash: str, delete_files=True, max_retry=2) -> tuple[bool, str]:
        info = self.info_map([torrent_hash])
        name = (info.get((torrent_hash or "").lower(), {}) or {}).get("name", f"<{torrent_hash[:12]}>")
        log.info(f"Suppression qB: '{name}' ({torrent_hash}), deleteFiles={delete_files}")
        if DRY_RUN:
            log.info(f"[DRY] would delete '{name}'"); return True, name

        for attempt in range(max_retry + 1):
            r = self.sess.post(f"{QBIT_HOST}/api/v2/torrents/delete",
                               data={"hashes": torrent_hash,
                                     "deleteFiles": "true" if delete_files else "false"},
                               timeout=REQ_TIMEOUT)
            if r.status_code not in (200, 415):
                log.warning(f"Delete returned {r.status_code}: {r.text[:200]}")
            time.sleep(0.4)
            still = self.info_map([torrent_hash])
            if (torrent_hash or "").lower() not in still:
                return True, name
            log.warning(f"Tentative {attempt+1}/{max_retry}: toujours présent '{name}'")
        return False, name
