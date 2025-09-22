import os, json, time, threading
from typing import Any, Optional

# ---- paramètres (surclassables via ENV dans docker-compose) ----
CACHE_FILE = os.environ.get("CLEANER_CACHE_FILE", "/app/data/cache.json")
CACHE_TTL  = int(os.environ.get("CLEANER_CACHE_TTL", "900"))      # 0 = jamais d'expiration
CACHE_MAX_ITEMS = int(os.environ.get("CLEANER_CACHE_MAX_ITEMS", "1000"))

_lock = threading.RLock()
_mem: dict[str, dict[str, Any]] = {}   # key -> {"latest": str|None, "candidates": [str], "ts": float}

def _now() -> float:
    return time.time()

def _expired(ts: float) -> bool:
    if CACHE_TTL == 0:    # cache infini
        return False
    return (_now() - ts) > CACHE_TTL

def _ensure_dir():
    d = os.path.dirname(CACHE_FILE)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)

def load_disk():
    global _mem
    try:
        _ensure_dir()
        if os.path.isfile(CACHE_FILE):
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                _mem.update(data)
    except Exception:
        pass

def save_disk():
    try:
        _ensure_dir()
        tmp = CACHE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_mem, f, ensure_ascii=False)
        os.replace(tmp, CACHE_FILE)
    except Exception:
        pass

def get(key: str) -> Optional[dict]:
    with _lock:
        ent = _mem.get(key)
        if not ent:
            return None
        if _expired(ent.get("ts", 0)):
            _mem.pop(key, None)
            return None
        return ent

def set(key: str, latest: Optional[str], candidates: list[str]):
    with _lock:
        # contrôle taille cache
        if len(_mem) >= CACHE_MAX_ITEMS:
            items = sorted(_mem.items(), key=lambda kv: kv[1].get("ts", 0))
            for k, _ in items[: max(1, len(items)//2)]:
                _mem.pop(k, None)
        _mem[key] = {
            "latest": (latest or None),
            "candidates": list(dict.fromkeys(candidates)),  # dédoublonne en gardant l'ordre
            "ts": _now()
        }
        save_disk()

def merge_candidates(key: str, new_candidates: list[str], latest: Optional[str] = None):
    """Ajoute des candidats et met éventuellement à jour latest."""
    with _lock:
        ent = _mem.get(key) or {"latest": None, "candidates": [], "ts": _now()}
        known = dict.fromkeys(ent.get("candidates", []))
        for h in new_candidates or []:
            if h:
                known[h] = None
        ent["candidates"] = list(known.keys())
        if latest:
            ent["latest"] = latest
        ent["ts"] = _now()
        _mem[key] = ent
        save_disk()

def touch_current(key: str, current_hash: str):
    """Marque le hash courant comme latest et l'ajoute aux candidats."""
    if not current_hash:
        return
    with _lock:
        ent = _mem.get(key) or {"latest": None, "candidates": [], "ts": _now()}
        if current_hash not in ent["candidates"]:
            ent["candidates"].append(current_hash)
        ent["latest"] = current_hash
        ent["ts"] = _now()
        _mem[key] = ent
        save_disk()

def prune_candidates(key: str, removed_hashes: list[str]):
    """Retire du cache les hashes supprimés dans qB."""
    if not removed_hashes:
        return
    with _lock:
        ent = _mem.get(key)
        if not ent:
            return
        s = set(removed_hashes)
        ent["candidates"] = [h for h in ent.get("candidates", []) if h not in s]
        if ent.get("latest") in s:
            ent["latest"] = None
        ent["ts"] = _now()
        save_disk()

# auto-chargement
load_disk()
