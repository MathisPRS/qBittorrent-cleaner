# app/tasks/seed_tags.py
"""
Reconcile des tags `seed` / `noseed` dans Radarr (films uniquement pour l'instant).

Critère = HARDLINK (inode) : un film est `seed` si son fichier médiathèque partage
son inode avec un fichier d'un torrent présent dans qBittorrent (1 copie physique
partagée = seed propre). Sinon `noseed`.

- Événementiel (import) : géré ailleurs (RadarrService → tag `seed` à l'import).
- Ici (planifié beat ~10h/22h) : filet de sécurité qui rattrape les SUPPRESSIONS et
  toute dérive (phantoms inclus : torrent "OK" mais fichier disparu → plus de hardlink
  → `noseed`). N'écrit QUE le delta (idempotent).

Nécessite que le conteneur worker monte le disque média (voir docker-compose : /nas-omv).
"""
import os
from app.extensions import celery
from app.adapters.radarr_adapter import RadarrAdapter
from app.adapters.qbittorrent_adapter import QbittorrentAdapter
from app.logger import get_logger

logger = get_logger(__name__)


def _torrent_inodes() -> set:
    """Ensemble des inodes de tous les fichiers de torrents présents sur le disque."""
    qb = QbittorrentAdapter()
    inodes = set()
    for t in qb.get_all_torrents():
        cp = (t.get("content_path") or "").strip()
        if not cp:
            continue
        try:
            if os.path.isfile(cp):
                inodes.add(os.stat(cp).st_ino)
            elif os.path.isdir(cp):
                for dp, _dirs, files in os.walk(cp):
                    for f in files:
                        try:
                            inodes.add(os.stat(os.path.join(dp, f)).st_ino)
                        except OSError:
                            pass
        except OSError:
            pass
    return inodes


@celery.task(name="seed.reconcile_seed_tags")
def reconcile_seed_tags() -> dict:
    radarr = RadarrAdapter()
    seed_id = radarr.get_or_create_tag("seed")
    noseed_id = radarr.get_or_create_tag("noseed")
    if seed_id is None or noseed_id is None:
        logger.error("[seed] impossible d'obtenir/créer les tags seed/noseed — abandon")
        return {"error": "tags"}

    inodes = _torrent_inodes()
    movies = radarr.get_all_movies()

    seeded = notseeded = changed = missing = 0
    for m in movies:
        if not m.get("hasFile"):
            continue
        path = (m.get("movieFile") or {}).get("path") or ""
        try:
            ino = os.stat(path).st_ino
        except OSError:
            missing += 1
            ino = None
        is_seed = ino is not None and ino in inodes
        tags = set(m.get("tags") or [])
        want = set(tags)
        if is_seed:
            want.discard(noseed_id); want.add(seed_id); seeded += 1
        else:
            want.discard(seed_id); want.add(noseed_id); notseeded += 1
        if want != tags:
            m["tags"] = sorted(want)
            if radarr.update_movie(m):
                changed += 1

    logger.info(
        "[seed] reconcile OK — seed=%d noseed=%d modifiés=%d (inodes_torrents=%d, fichiers_absents=%d)",
        seeded, notseeded, changed, len(inodes), missing,
    )
    return {"seed": seeded, "noseed": notseeded, "changed": changed, "torrent_inodes": len(inodes)}
