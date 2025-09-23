from .models import norm_hash

def promote_latest(entry: dict, current_hash: str):
    cur = norm_hash(current_hash)
    if entry.get("latest") != cur:
        old_latest = entry.get("latest")
        if old_latest and old_latest not in entry.get("candidates", []):
            entry["candidates"].append(old_latest)
        entry["latest"] = cur
    if cur and cur not in entry.get("candidates", []):
        entry["candidates"].append(cur)

def compute_to_delete(entry: dict) -> list[str]:
    latest = norm_hash(entry.get("latest"))
    removed = set(entry.get("removed") or [])
    out = []
    for h in entry.get("candidates", []):
        hh = norm_hash(h)
        if hh and hh != latest and hh not in removed:
            out.append(hh)
    seen, dedup = set(), []
    for h in out:
        if h not in seen:
            seen.add(h)
            dedup.append(h)
    return dedup

def mark_removed(entry: dict, removed_hashes: list[str]):
    rs = set(entry.get("removed") or [])
    for h in removed_hashes:
        if h:
            rs.add(norm_hash(h))
    entry["removed"] = list(sorted(rs))
