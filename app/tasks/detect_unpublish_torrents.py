# app/tasks/detect_unpublish_torrents.py
"""
QbTorrentAuditService
=====================
Daily audit that ensures the local DB stays in sync with qBittorrent and that
no orphaned torrent files accumulate on disk.

Two-phase pipeline
------------------

Phase 1 — DB sync (qBittorrent diff)
    Compare every torrent currently in qBittorrent against the local DB.
    Torrents present in qBittorrent but absent from the DB indicate a missed
    webhook.  Each unknown torrent is resolved against Sonarr/Radarr and
    ingested so that future upgrades are handled correctly.

    Guard: torrents that are in the Radarr or Sonarr download queue (e.g.
    awaiting a manual import interaction) are excluded from the "unknown" list
    even if they are not yet in the DB.

Phase 2 — Hardlink audit (orphan detection)
    After the DB is in sync, scan every seeding torrent's files for a hard
    link count of 1.  A count of 1 means the file is no longer linked to the
    media library (/media) — Radarr/Sonarr has already replaced it with a
    better version.  Such torrents are queued for deletion through the normal
    DeferredDeletionService pipeline (respects seeding-time delta, Celery
    scheduling, Gotify notifications, etc.).

    Guard: same as Phase 1 — torrents present in the arr queues are skipped.

Can be run:
  • As a CLI script  : python -m app.tasks.detect_unpublish_torrents [--dry-run]
  • As a Celery task : celery.send_task("audit.sync_unknown_torrents")
"""

import sys
from typing import Dict, List, Optional, Set

from app import create_app
from app.extensions import celery
from app.logger import get_logger
from app.models.torrents import Torrents
from app.adapters.qbittorrent_adapter import QbittorrentAdapter
from app.services.torrents_resolver_services import TorrentResolverService
from app.services.radarr_services import RadarrService
from app.services.sonarr_services import SonarrService
from app.services.commun_services import CommunService
from app.services.arr_queue_service import ArrQueueService
from app.services.hardlink_audit_service import HardlinkAuditService
from app.services.deferred_deletions_services import DeferredDeletionService
from app.repositories.torrents_repo import TorrentsRepo
from app.adapters.gotify_adapter import notify_gotify


# qBittorrent categories mapped to each content type
_FILM_CATEGORIES: Set[str] = {"films"}
_SERIES_CATEGORIES: Set[str] = {"series", "animes"}
_IGNORED_CATEGORIES: Set[str] = {"adultes", "autres"}

# qBittorrent tag that marks cross-seed copies
_CROSS_SEED_TAG = "cross-seed"


class QbTorrentAuditService:
    """
    Orchestrates the two-phase daily audit:

      Phase 1 — DB sync
        Finds torrents present in qBittorrent but missing from the DB (missed
        webhooks), resolves them against Sonarr/Radarr, and ingests them.

      Phase 2 — Hardlink audit
        Finds seeding torrents whose files are no longer hardlinked to /media
        (orphaned after an upgrade) and queues them for deletion.

    Both phases exclude torrents that are currently managed by Radarr/Sonarr
    (present in their download queues) to avoid interfering with pending or
    manual imports.
    """

    def __init__(self, app, dry_run: bool = False):
        self.app = app
        self.dry_run = dry_run
        self.logger = get_logger(__name__, app=app)

        # Adapters
        self.qb = QbittorrentAdapter()

        # Services — Phase 1
        self.resolver = TorrentResolverService(app)
        self.radarr_service = RadarrService(app)
        self.sonarr_service = SonarrService(app)
        self.commun_service = CommunService(app)
        self.torrents_repo = TorrentsRepo()

        # Services — shared guard (both phases)
        self.arr_queue_service = ArrQueueService()

        # Services — Phase 2
        self.hardlink_audit_service = HardlinkAuditService()
        self.deferred_deletion_service = DeferredDeletionService(app)

        self._unresolved: list = []

    # ----------------------------------------------------------------
    # Public entrypoint
    # ----------------------------------------------------------------

    def run(self) -> Dict:
        self.logger.info("===== START QB TORRENT AUDIT =====")

        # Fetch the arr queues once — reused by both phases as a guard
        managed_hashes = self.arr_queue_service.get_managed_hashes()
        self.logger.info(
            "[Audit] arr-managed hashes (queue guard): %d", len(managed_hashes)
        )

        # Fetch the live qBittorrent torrent list once — reused by both phases
        qb_torrents = self._get_qb_torrents()
        self.logger.info("[Audit] qBittorrent torrents count: %d", len(qb_torrents))

        # ------------------------------------------------------------------
        # Phase 1: DB sync — ingest torrents missing from the DB
        # ------------------------------------------------------------------
        phase1_stats = self._run_phase1_db_sync(qb_torrents, managed_hashes)

        # ------------------------------------------------------------------
        # Phase 2: Hardlink audit — queue orphaned torrents for deletion
        # ------------------------------------------------------------------
        phase2_stats = self._run_phase2_hardlink_audit(qb_torrents, managed_hashes)

        # ------------------------------------------------------------------
        # Wrap-up
        # ------------------------------------------------------------------
        self.logger.info(
            "===== END QB TORRENT AUDIT ===== "
            "phase1[unknown=%d ingested=%d skipped=%d failed=%d] "
            "phase2[orphaned=%d queued_deletion=%d]",
            phase1_stats["total_unknown"],
            phase1_stats["ingested"],
            phase1_stats["skipped"],
            phase1_stats["failed"],
            phase2_stats["orphaned"],
            phase2_stats["queued_deletion"],
        )

        if self._unresolved:
            try:
                lines = [f"{item['name']} — {item['reason']}" for item in self._unresolved]
                notify_gotify("Webhook Cleaner : Audit — torrents non résolus", lines)
            except Exception:
                self.logger.exception(
                    "[Audit] Failed to send Gotify notification for unresolved torrents"
                )

        return {
            "phase1": phase1_stats,
            "phase2": phase2_stats,
        }

    # ----------------------------------------------------------------
    # Phase 1: DB sync
    # ----------------------------------------------------------------

    def _run_phase1_db_sync(
        self,
        qb_torrents: List[dict],
        managed_hashes: Set[str],
    ) -> Dict:
        """
        Compares qBittorrent torrents against the local DB and ingests any
        torrent that is missing, provided it is not currently managed by an
        arr queue.
        """
        self.logger.info("[Phase1] Starting DB sync")

        db_hashes = self._get_db_hashes()
        self.logger.info("[Phase1] DB hashes count: %d", len(db_hashes))

        unknown_torrents = self._filter_unknown(qb_torrents, db_hashes, managed_hashes)

        if not unknown_torrents:
            self.logger.info("[Phase1] No unknown torrents — DB is in sync")
            return {"total_unknown": 0, "ingested": 0, "skipped": 0, "failed": 0}

        self.logger.warning(
            "[Phase1] %d torrent(s) in qBittorrent but NOT in DB", len(unknown_torrents)
        )

        films, series_anime, cross_seeds, unclassified = self._classify(unknown_torrents)
        self.logger.info(
            "[Phase1] Classified: films=%d series/anime=%d cross_seeds=%d unclassified=%d",
            len(films), len(series_anime), len(cross_seeds), len(unclassified),
        )

        stats = {"ingested": 0, "skipped": 0, "failed": 0}

        for torrent in films:
            self._process_film(torrent, stats)

        for torrent in series_anime:
            self._process_series(torrent, stats)

        for torrent in cross_seeds:
            self._process_cross_seed(torrent, stats)

        for torrent in unclassified:
            self.logger.warning(
                "[Phase1] Unclassified torrent skipped: hash=%s name=%s category=%s tags=%s",
                torrent.get("hash"), torrent.get("name"),
                torrent.get("category"), torrent.get("tags"),
            )
            stats["skipped"] += 1

        return {
            "total_unknown": len(unknown_torrents),
            "ingested":      stats["ingested"],
            "skipped":       stats["skipped"],
            "failed":        stats["failed"],
        }

    # ----------------------------------------------------------------
    # Phase 2: Hardlink audit
    # ----------------------------------------------------------------

    def _run_phase2_hardlink_audit(
        self,
        qb_torrents: List[dict],
        managed_hashes: Set[str],
    ) -> Dict:
        """
        Scans seeding torrents for files with st_nlink == 1 (no longer linked
        to /media) and queues them for deletion via DeferredDeletionService.

        Torrents present in the arr queues are excluded — they may legitimately
        have st_nlink == 1 while waiting for a manual import action.
        """
        self.logger.info("[Phase2] Starting hardlink audit")

        orphaned_hashes = self.hardlink_audit_service.find_orphaned_hashes(
            qb_torrents=qb_torrents,
            managed_hashes=managed_hashes,
        )

        if not orphaned_hashes:
            self.logger.info("[Phase2] No orphaned torrents found")
            return {"orphaned": 0, "queued_deletion": 0}

        self.logger.warning(
            "[Phase2] %d orphaned torrent(s) detected — routing to deletion pipeline",
            len(orphaned_hashes),
        )

        # Build a quick lookup map hash → torrent info for the print below
        qb_by_hash = {
            (t.get("hash") or "").strip().lower(): t
            for t in qb_torrents
        }

        self.logger.info("[Phase2] ===== ORPHANED TORRENTS (no hardlink to /media) =====")
        for i, h in enumerate(orphaned_hashes, start=1):
            info = qb_by_hash.get(h, {})
            name         = info.get("name") or "<unknown>"
            category     = info.get("category") or "<unknown>"
            content_path = info.get("content_path") or "<unknown>"
            state        = info.get("state") or "<unknown>"
            size_bytes   = info.get("size") or 0
            size_gb      = size_bytes / (1024 ** 3) if size_bytes else 0
            self.logger.info(
                "[Phase2]  [%d/%d] hash=%-40s  name=%s  category=%s  state=%s  size=%.2f GB  path=%s",
                i, len(orphaned_hashes),
                h, name, category, state, size_gb, content_path,
            )
        self.logger.info("[Phase2] ===== END OF ORPHANED TORRENTS LIST =====")

        if self.dry_run:
            self.logger.info(
                "[Phase2][DRY_RUN] Would queue %d hashes for deletion: %s",
                len(orphaned_hashes), orphaned_hashes,
            )
            return {"orphaned": len(orphaned_hashes), "queued_deletion": 0}

        # Route through the standard deferred-deletion pipeline:
        # immediately-deletable hashes are deleted now; others are scheduled
        # via Celery with the seeding-time delta (same flow as a webhook upgrade).
        ready_to_delete = self.deferred_deletion_service.filter_deferred_deletion_hash(
            orphaned_hashes
        )

        if ready_to_delete:
            self.commun_service.perform_deletion(ready_to_delete)
            self.logger.info(
                "[Phase2] Deletion triggered for %d hash(es)", len(ready_to_delete)
            )

        deferred_count = len(orphaned_hashes) - len(ready_to_delete)
        if deferred_count:
            self.logger.info(
                "[Phase2] %d hash(es) deferred — scheduled via Celery", deferred_count
            )

        return {
            "orphaned":        len(orphaned_hashes),
            "queued_deletion": len(ready_to_delete),
        }

    # ----------------------------------------------------------------
    # Phase 1 helpers — ingestion
    # ----------------------------------------------------------------

    def _process_film(self, torrent: dict, stats: dict) -> None:
        name  = torrent.get("name") or ""
        hash_ = torrent.get("hash") or ""

        self.logger.info("[Phase1] Processing FILM: hash=%s name=%s", hash_, name)

        resolution = self._resolve(name, hash_)
        if not resolution or resolution.get("type") == "unresolved":
            reason = (resolution or {}).get("reason", "resolve_failed")
            self.logger.warning(
                "[Phase1] FILM unresolved: hash=%s name=%s reason=%s", hash_, name, reason
            )
            self._unresolved.append({"name": name, "hash": hash_, "reason": reason})
            stats["skipped"] += 1
            return

        if resolution["type"] != "movie":
            self.logger.warning(
                "[Phase1] FILM resolved as '%s' (not movie): hash=%s — delegating to series path",
                resolution["type"], hash_,
            )
            self._ingest_series_resolution(hash_, name, resolution, stats)
            return

        if self.dry_run:
            self.logger.info(
                "[Phase1][DRY_RUN] Would ingest movie: radarr_id=%s title=%s hash=%s",
                resolution.get("radarr_id"), resolution.get("radarr_title"), hash_,
            )
            stats["skipped"] += 1
            return

        dto = {
            "torrent":   {"hash": hash_, "sourcePath": name},
            "radarr_id": resolution.get("radarr_id"),
            "title":     resolution.get("radarr_title") or resolution.get("title"),
            "image":     None,
        }
        result = self.radarr_service.import_completed_movie(dto)
        self._record_stats(result, stats, hash_, name)

    def _process_series(self, torrent: dict, stats: dict) -> None:
        name  = torrent.get("name") or ""
        hash_ = torrent.get("hash") or ""

        self.logger.info("[Phase1] Processing SERIES/ANIME: hash=%s name=%s", hash_, name)

        resolution = self._resolve(name, hash_)
        if not resolution or resolution.get("type") == "unresolved":
            reason = (resolution or {}).get("reason", "resolve_failed")
            self.logger.warning(
                "[Phase1] SERIES unresolved: hash=%s name=%s reason=%s", hash_, name, reason
            )
            self._unresolved.append({"name": name, "hash": hash_, "reason": reason})
            stats["skipped"] += 1
            return

        self._ingest_series_resolution(hash_, name, resolution, stats)

    def _ingest_series_resolution(
        self, hash_: str, name: str, resolution: dict, stats: dict
    ) -> None:
        if resolution["type"] != "episode":
            self.logger.warning(
                "[Phase1] Expected 'episode' resolution but got '%s': hash=%s name=%s",
                resolution["type"], hash_, name,
            )
            stats["skipped"] += 1
            return

        if self.dry_run:
            self.logger.info(
                "[Phase1][DRY_RUN] Would ingest series: sonarr_id=%s title=%s episodes=%d hash=%s",
                resolution.get("sonarr_id"), resolution.get("sonarr_title"),
                len(resolution.get("episodes") or []), hash_,
            )
            stats["skipped"] += 1
            return

        dto = {
            "torrent":   {"hash": hash_, "sourcePath": name},
            "sonarr_id": resolution.get("sonarr_id"),
            "title":     resolution.get("sonarr_title") or resolution.get("title"),
            "image":     None,
            "episodes":  resolution.get("episodes") or [],
        }
        result = self.sonarr_service.import_completed_episodes(dto)
        self._record_stats(result, stats, hash_, name)

    def _process_cross_seed(self, torrent: dict, stats: dict) -> None:
        name  = torrent.get("name") or ""
        hash_ = torrent.get("hash") or ""

        self.logger.info("[Phase1] Processing CROSS-SEED: hash=%s name=%s", hash_, name)

        if self.dry_run:
            self.logger.info(
                "[Phase1][DRY_RUN] Would ingest cross-seed: hash=%s name=%s", hash_, name
            )
            stats["skipped"] += 1
            return

        parent = None
        try:
            parent = self.torrents_repo.get_parent_by_name(name=name, parent_hash=None)
        except Exception:
            self.logger.exception("[Phase1] get_parent_by_name failed for name=%s", name)

        if parent is None:
            self.logger.warning(
                "[Phase1] Cross-seed parent NOT found for name=%s hash=%s — skipping",
                name, hash_,
            )
            stats["skipped"] += 1
            return

        child = self.commun_service.ensure_torrent_exists(hash_, name)
        if not child:
            self.logger.error(
                "[Phase1] Could not create child torrent row for hash=%s", hash_
            )
            stats["failed"] += 1
            return

        try:
            linked = self.torrents_repo.set_cross_seed_parent(
                child_hash=hash_,
                parent_id=parent.id,
                child_name=name,
            )
        except Exception:
            self.logger.exception(
                "[Phase1] set_cross_seed_parent failed for hash=%s", hash_
            )
            stats["failed"] += 1
            return

        if linked:
            self.logger.info(
                "[Phase1] Cross-seed linked: child_hash=%s parent_id=%s", hash_, parent.id
            )
            stats["ingested"] += 1
        else:
            self.logger.warning(
                "[Phase1] Cross-seed link failed: child_hash=%s parent_id=%s", hash_, parent.id
            )
            stats["failed"] += 1

    # ----------------------------------------------------------------
    # Shared helpers
    # ----------------------------------------------------------------

    def _classify(self, torrents: List[dict]):
        films:          List[dict] = []
        series_anime:   List[dict] = []
        cross_seeds:    List[dict] = []
        unclassified:   List[dict] = []

        for t in torrents:
            category = (t.get("category") or "").strip().lower()
            tags = [tag.strip().lower() for tag in str(t.get("tags") or "").split(",")]

            if _CROSS_SEED_TAG in tags:
                cross_seeds.append(t)
            elif category in _FILM_CATEGORIES:
                films.append(t)
            elif category in _SERIES_CATEGORIES:
                series_anime.append(t)
            else:
                unclassified.append(t)

        return films, series_anime, cross_seeds, unclassified

    def _resolve(self, torrent_name: str, torrent_hash: str) -> Optional[Dict]:
        try:
            return self.resolver.resolve_torrent(torrent_name)
        except Exception:
            self.logger.exception(
                "[Phase1] resolve_torrent raised for hash=%s name=%s",
                torrent_hash, torrent_name,
            )
            return None

    def _record_stats(
        self, result: Optional[dict], stats: dict, hash_: str, name: str
    ) -> None:
        if not result:
            self.logger.error(
                "[Phase1] Ingest returned None for hash=%s name=%s", hash_, name
            )
            stats["failed"] += 1
            return

        action = result.get("action", "")
        if action == "error":
            self.logger.warning(
                "[Phase1] Ingest failed: hash=%s name=%s result=%s", hash_, name, result
            )
            stats["failed"] += 1
        elif action == "ignored":
            self.logger.info(
                "[Phase1] Ignored (already up-to-date): hash=%s name=%s", hash_, name
            )
            stats["skipped"] += 1
        else:
            self.logger.info("[Phase1] %s: hash=%s name=%s", action, hash_, name)
            stats["ingested"] += 1

    # ----------------------------------------------------------------
    # qBittorrent helpers
    # ----------------------------------------------------------------

    def _get_qb_torrents(self) -> List[dict]:
        try:
            self.qb.login()
        except Exception:
            self.logger.exception("[Audit] Failed to login to qBittorrent")
            return []

        try:
            return self.qb.get_all_torrents()
        except Exception:
            self.logger.exception("[Audit] Failed to fetch torrents from qBittorrent")
            return []

    def _get_db_hashes(self) -> Set[str]:
        db_torrents = Torrents.query.all()
        return {
            (t.hash or "").strip().lower()
            for t in db_torrents
            if t.hash
        }

    def _filter_unknown(
        self,
        qb_torrents: List[dict],
        db_hashes: Set[str],
        managed_hashes: Set[str],
    ) -> List[dict]:
        """
        Returns torrents that are:
          - present in qBittorrent
          - absent from the local DB
          - NOT currently managed by Radarr/Sonarr (not in their queues)
          - not in an ignored category
        """
        unknown = []
        for torrent in qb_torrents:
            hash_    = (torrent.get("hash") or "").strip().lower()
            category = (torrent.get("category") or "").strip().lower()

            if not hash_:
                continue
            if category in _IGNORED_CATEGORIES:
                continue
            if hash_ in db_hashes:
                continue
            if hash_ in managed_hashes:
                self.logger.debug(
                    "[Phase1] hash=%s is not in DB but is in arr queue — skipping (pending import)",
                    hash_,
                )
                continue

            unknown.append(torrent)

        return unknown


# ================================================================
# Celery task
# ================================================================

@celery.task(name="audit.sync_unknown_torrents", bind=True, max_retries=2)
def sync_unknown_torrents(self):
    """
    Celery task: run the two-phase daily audit.
      - Phase 1: ingest qBittorrent torrents missing from the DB
      - Phase 2: queue orphaned (non-hardlinked) torrents for deletion
    Scheduled via Celery Beat or triggered on demand.
    Requires AUDIT_ENABLED = True in configlocal.cfg [celery] to run automatically.
    """
    from flask import current_app
    from app.config import AUDIT_ENABLED

    app = current_app._get_current_object()

    if not AUDIT_ENABLED:
        app.logger.info(
            "sync_unknown_torrents: AUDIT_ENABLED=False — skipped "
            "(set [celery] AUDIT_ENABLED = True in configlocal.cfg to enable)"
        )
        return {"skipped": True, "reason": "AUDIT_ENABLED=False"}

    service = QbTorrentAuditService(app, dry_run=False)
    try:
        return service.run()
    except Exception as exc:
        app.logger.exception("sync_unknown_torrents: unexpected error")
        raise self.retry(exc=exc, countdown=120)


# ================================================================
# CLI entrypoint
# ================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Two-phase audit: sync qBittorrent→DB and detect orphaned hardlinks"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve and log what would be ingested/deleted without writing anything",
    )
    parser.add_argument(
        "--hardlink-only",
        action="store_true",
        help=(
            "Only run the hardlink audit (Phase 2): print all orphaned torrents "
            "(files with st_nlink == 1) without deleting or modifying anything. "
            "Implies --dry-run for Phase 2."
        ),
    )
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        if args.hardlink_only:
            # Instantiate directly to skip Phase 1 entirely
            service = QbTorrentAuditService(app, dry_run=True)
            managed_hashes = service.arr_queue_service.get_managed_hashes()
            qb_torrents    = service._get_qb_torrents()
            service._run_phase2_hardlink_audit(qb_torrents, managed_hashes)
        else:
            service = QbTorrentAuditService(app, dry_run=args.dry_run)
            service.run()


if __name__ == "__main__":
    main()
