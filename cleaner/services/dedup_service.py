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

    # union des candidats à supprimer sur tous les épisodes concernés
    to_delete = set()
    for eid in episode_ids:
        entry = s.get("episodes", {}).get(str(eid))
        if entry:
            to_delete.update(compute_to_delete(entry))
    to_delete = list(sorted(to_delete))

    client = QbitClient(); client.login()

    # --- suppression groupée ---
    result = client.delete_many(to_delete, delete_files=True)
    # absent = pas/plus dans qB (déjà parti)
    already_gone.extend(result.get("absent", []))

    # mappe les résultats pour MAJ des tombstones
    if result.get("deleted"):
        # tuples (hash, name)
        removed.extend([{"hash": h, "name": name} for (h, name) in result["deleted"]])
    if result.get("failed"):
        errors.extend([{"hash": h, "name": name} for (h, name) in result["failed"]])

    # MAJ tombstones si on a supprimé des choses
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

    # --- suppression groupée ---
    result = client.delete_many(to_delete, delete_files=True)
    already_gone.extend(result.get("absent", []))

    if result.get("deleted"):
        removed.extend([{"hash": h, "name": name} for (h, name) in result["deleted"]])
    if result.get("failed"):
        errors.extend([{"hash": h, "name": name} for (h, name) in result["failed"]])

    if removed:
        mark_removed(entry, [x["hash"] for x in removed])
        catalog_repo.save_catalog(cat)
        notify_gotify(f"Dédup (Radarr) {label}", [r["name"] for r in removed])

    return removed, already_gone, errors
