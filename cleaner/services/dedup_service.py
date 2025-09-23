import logging
from ..repositories import catalog_repo
from ..domain.rules import compute_to_delete, mark_removed
from ..adapters.qbittorrent import QbitClient
from ..adapters.gotify import notify_gotify

log = logging.getLogger("webhook-cleaner")

def purge_for_episodes(series_id: int, episode_ids: list[int], label: str):
    cat = catalog_repo.load_catalog()
    s = cat["sonarr"].get(str(series_id)) or {}
    removed, already_gone, errors = [], [], []

    to_delete = set()
    for eid in episode_ids:
        entry = s.get("episodes", {}).get(str(eid))
        if entry:
            to_delete.update(compute_to_delete(entry))

    client = QbitClient(); client.login()
    present_map = client.info_map(list(to_delete))
    for h in to_delete:
        if h not in present_map:
            already_gone.append(h); continue
        ok, name = client.delete(h, delete_files=True, max_retry=2)
        if ok:
            removed.append({"hash": h, "name": name})
        else:
            errors.append({"hash": h, "name": name})

    if removed:
        hashes = [x["hash"] for x in removed]
        for eid in episode_ids:
            entry = s.get("episodes", {}).get(str(eid))
            if entry:
                mark_removed(entry, hashes)
        catalog_repo.save_catalog(cat)
        notify_gotify(f"Dédup (Sonarr) {label}", [r["name"] for r in removed])

    return removed, already_gone, errors

def purge_for_movie(movie_id: int, label: str):
    cat = catalog_repo.load_catalog()
    entry = cat["radarr"].get(str(movie_id)) or {}
    removed, already_gone, errors = [], [], []

    to_delete = compute_to_delete(entry)

    client = QbitClient(); client.login()
    present_map = client.info_map(to_delete)
    for h in to_delete:
        if h not in present_map:
            already_gone.append(h); continue
        ok, name = client.delete(h, delete_files=True, max_retry=2)
        if ok:
            removed.append({"hash": h, "name": name})
        else:
            errors.append({"hash": h, "name": name})

    if removed:
        mark_removed(entry, [x["hash"] for x in removed])
        catalog_repo.save_catalog(cat)
        notify_gotify(f"Dédup (Radarr) {label}", [r["name"] for r in removed])

    return removed, already_gone, errors
