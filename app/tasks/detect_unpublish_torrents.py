# app/tasks/detect_unpublish_torrents.py
"""
QbTorrentAuditService  (merged detect_unpublish_torrents + get_data_from_radarr)
=================================================================================
Scans every torrent currently in qBittorrent, compares against the local DB,
and for each unknown torrent:

  - Films   → resolves via Radarr then inserts Movie + Torrent into DB
  - Series  → resolves via Sonarr then inserts Series + Episodes + Torrent into DB
  - Animes  → same as Series (treated as Sonarr content)
  - Cross-seed torrents (tag "cross-seed") → create child Torrent row, link to parent

Torrents in ignored categories ("adultes", "autres") are skipped.

Can be run:
  • As a CLI script   : python -m app.tasks.detect_unpublish_torrents [--dry-run]
  • As a Celery task  : celery.send_task("audit.sync_unknown_torrents")
"""

import sys
from typing import Dict, List, Optional

from app import create_app
from app.extensions import celery
from app.logger import get_logger
from app.models.torrents import Torrents
from app.adapters.qbittorrent_adapter import QbittorrentAdapter
from app.services.torrents_resolver_services import TorrentResolverService
from app.services.ingest_service import IngestService


# Categories qBittorrent uses for each content type
_FILM_CATEGORIES = {"films"}
_SERIES_CATEGORIES = {"series", "animes"}
_IGNORED_CATEGORIES = {"adultes", "autres"}

# qBittorrent tag that marks cross-seed copies
_CROSS_SEED_TAG = "cross-seed"


class QbTorrentAuditService:
    """
    Full pipeline:
      1. Fetch all torrents from qBittorrent
      2. Compare against DB hashes
      3. For each unknown torrent:
           - classify by category / tag
           - resolve against Sonarr/Radarr
           - ingest into DB (Torrent + Movie/Series/Episodes)
    """

    def __init__(self, app, dry_run: bool = False):
        self.app = app
        self.dry_run = dry_run
        self.logger = get_logger(__name__, app=app)
        self.qb = QbittorrentAdapter()
        self.resolver = TorrentResolverService(app)
        self.ingest = IngestService(app)

    # ----------------------------------------------------------------
    # Public entrypoint
    # ----------------------------------------------------------------

    def run(self) -> Dict:
        self.logger.info("===== START QB TORRENT AUDIT =====")

        # --- Step 1: known DB hashes --------------------------------
        db_torrents = Torrents.query.all()
        db_hashes = {
            (t.hash or "").strip().lower()
            for t in db_torrents
            if t.hash
        }
        self.logger.info("DB torrents count: %d", len(db_hashes))

        # --- Step 2: live qBittorrent list --------------------------
        qb_torrents = self._get_qb_torrents()
        self.logger.info("qBittorrent torrents count: %d", len(qb_torrents))

        # --- Step 3: filter unknowns --------------------------------
        unknown = self._filter_unknown(qb_torrents, db_hashes)
        if not unknown:
            self.logger.info("No unknown torrents found — DB is in sync")
            self.logger.info("===== END QB TORRENT AUDIT =====")
            return {"total_unknown": 0, "ingested": 0, "skipped": 0, "failed": 0}

        self.logger.warning("Found %d torrent(s) in qBittorrent but NOT in DB", len(unknown))

        # --- Step 4: classify ---------------------------------------
        films, series_anime, cross_seeds, unclassified = self._classify(unknown)

        self.logger.info("Classified: films=%d series/anime=%d cross_seeds=%d unclassified=%d",
                         len(films), len(series_anime), len(cross_seeds), len(unclassified))

        # --- Step 5: process each group ----------------------------
        stats = {"ingested": 0, "skipped": 0, "failed": 0}

        for torrent in films:
            self._process_film(torrent, stats)

        for torrent in series_anime:
            self._process_series(torrent, stats)

        for torrent in cross_seeds:
            self._process_cross_seed(torrent, stats)

        for torrent in unclassified:
            self.logger.warning(
                "[Audit] Unclassified torrent — no category/tag matched: "
                "hash=%s name=%s category=%s tags=%s",
                torrent.get("hash"), torrent.get("name"),
                torrent.get("category"), torrent.get("tags"),
            )
            stats["skipped"] += 1

        total_unknown = len(unknown)
        self.logger.info(
            "===== END QB TORRENT AUDIT ===== "
            "total_unknown=%d ingested=%d skipped=%d failed=%d",
            total_unknown, stats["ingested"], stats["skipped"], stats["failed"],
        )
        return {
            "total_unknown": total_unknown,
            "ingested": stats["ingested"],
            "skipped": stats["skipped"],
            "failed": stats["failed"],
        }

    # ----------------------------------------------------------------
    # Step helpers
    # ----------------------------------------------------------------

    def _process_film(self, torrent: dict, stats: dict) -> None:
        name = torrent.get("name") or ""
        hash_ = torrent.get("hash") or ""

        self.logger.info("[Audit] Processing FILM: hash=%s name=%s", hash_, name)

        resolution = self._resolve(name, hash_)
        if not resolution or resolution.get("type") == "unresolved":
            reason = (resolution or {}).get("reason", "resolve_failed")
            self.logger.warning("[Audit] FILM unresolved: hash=%s name=%s reason=%s",
                                hash_, name, reason)
            stats["skipped"] += 1
            return

        if resolution["type"] != "movie":
            self.logger.warning(
                "[Audit] FILM torrent resolved as '%s' (not movie): hash=%s name=%s — processing as series",
                resolution["type"], hash_, name,
            )
            # guessit sometimes flips type; delegate to series path
            self._ingest_series_resolution(hash_, name, resolution, stats)
            return

        if self.dry_run:
            self.logger.info("[DRY_RUN] Would ingest movie: radarr_id=%s title=%s hash=%s",
                             resolution.get("radarr_id"), resolution.get("radarr_title"), hash_)
            stats["skipped"] += 1
            return

        result = self.ingest.ingest_movie(hash_, name, resolution)
        self._record_stats(result, stats, hash_, name)

    def _process_series(self, torrent: dict, stats: dict) -> None:
        name = torrent.get("name") or ""
        hash_ = torrent.get("hash") or ""

        self.logger.info("[Audit] Processing SERIES/ANIME: hash=%s name=%s", hash_, name)

        resolution = self._resolve(name, hash_)
        if not resolution or resolution.get("type") == "unresolved":
            reason = (resolution or {}).get("reason", "resolve_failed")
            self.logger.warning("[Audit] SERIES unresolved: hash=%s name=%s reason=%s",
                                hash_, name, reason)
            stats["skipped"] += 1
            return

        self._ingest_series_resolution(hash_, name, resolution, stats)

    def _ingest_series_resolution(self, hash_: str, name: str, resolution: dict, stats: dict) -> None:
        if resolution["type"] != "episode":
            self.logger.warning("[Audit] Expected 'episode' resolution but got '%s': hash=%s name=%s",
                                resolution["type"], hash_, name)
            stats["skipped"] += 1
            return

        if self.dry_run:
            self.logger.info(
                "[DRY_RUN] Would ingest series: sonarr_id=%s title=%s episodes=%d hash=%s",
                resolution.get("sonarr_id"), resolution.get("sonarr_title"),
                len(resolution.get("episodes") or []), hash_,
            )
            stats["skipped"] += 1
            return

        result = self.ingest.ingest_series(hash_, name, resolution)
        self._record_stats(result, stats, hash_, name)

    def _process_cross_seed(self, torrent: dict, stats: dict) -> None:
        name = torrent.get("name") or ""
        hash_ = torrent.get("hash") or ""

        self.logger.info("[Audit] Processing CROSS-SEED: hash=%s name=%s", hash_, name)

        if self.dry_run:
            self.logger.info("[DRY_RUN] Would ingest cross-seed: hash=%s name=%s", hash_, name)
            stats["skipped"] += 1
            return

        result = self.ingest.ingest_cross_seed(hash_, name)
        self._record_stats(result, stats, hash_, name)

    # ----------------------------------------------------------------
    # Classify
    # ----------------------------------------------------------------

    def _classify(self, torrents: List[dict]):
        films: List[dict] = []
        series_anime: List[dict] = []
        cross_seeds: List[dict] = []
        unclassified: List[dict] = []

        for t in torrents:
            category = (t.get("category") or "").strip().lower()
            tags_raw = t.get("tags") or ""
            tags = [tag.strip().lower() for tag in str(tags_raw).split(",")]

            if _CROSS_SEED_TAG in tags:
                cross_seeds.append(t)
                continue

            if category in _FILM_CATEGORIES:
                films.append(t)
            elif category in _SERIES_CATEGORIES:
                series_anime.append(t)
            else:
                unclassified.append(t)

        return films, series_anime, cross_seeds, unclassified

    # ----------------------------------------------------------------
    # Resolve (wrapper with exception guard)
    # ----------------------------------------------------------------

    def _resolve(self, torrent_name: str, torrent_hash: str) -> Optional[Dict]:
        try:
            return self.resolver.resolve_torrent(torrent_name)
        except Exception:
            self.logger.exception("[Audit] resolve_torrent raised for hash=%s name=%s",
                                  torrent_hash, torrent_name)
            return None

    # ----------------------------------------------------------------
    # Stats helper
    # ----------------------------------------------------------------

    def _record_stats(self, result: Optional[dict], stats: dict, hash_: str, name: str) -> None:
        if not result:
            self.logger.error("[Audit] Ingest returned None for hash=%s name=%s", hash_, name)
            stats["failed"] += 1
            return

        if result.get("ok"):
            action = result.get("action", "ingested")
            if action == "skipped":
                stats["skipped"] += 1
            else:
                stats["ingested"] += 1
            self.logger.info("[Audit] %s: hash=%s name=%s", action, hash_, name)
        else:
            reason = result.get("reason", "unknown")
            self.logger.warning("[Audit] Ingest failed: hash=%s name=%s reason=%s", hash_, name, reason)
            stats["failed"] += 1

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
            # use the public adapter method which already handles the client access
            raw_list = self.qb.get_all_torrents()
            result = []
            for t in raw_list:
                h = t.get("hash") or ""
                result.append({
                    "hash": str(h).lower() if h else "",
                    "name": t.get("name"),
                    "category": t.get("category") or "",
                    "tags": t.get("tags") or "",
                })
            return result
        except Exception:
            self.logger.exception("[Audit] Failed to fetch torrents from qBittorrent")
            return []

    def _filter_unknown(self, qb_torrents: List[dict], db_hashes: set) -> List[dict]:
        unknown = []
        for t in qb_torrents:
            hash_ = (t.get("hash") or "").strip().lower()
            if not hash_:
                continue
            category = (t.get("category") or "").strip().lower()
            if category in _IGNORED_CATEGORIES:
                continue
            if hash_ not in db_hashes:
                unknown.append(t)
        return unknown


# ================================================================
# Celery task
# ================================================================

@celery.task(name="audit.sync_unknown_torrents", bind=True, max_retries=2)
def sync_unknown_torrents(self):
    """
    Celery task: audit qBittorrent against DB and ingest missing torrents.
    Scheduled on-demand or via beat.
    """
    from flask import current_app
    app = current_app._get_current_object()
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
    parser = argparse.ArgumentParser(description="Audit qBittorrent vs DB and ingest missing torrents")
    parser.add_argument("--dry-run", action="store_true",
                        help="Resolve and log what would be ingested without writing to DB")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        service = QbTorrentAuditService(app, dry_run=args.dry_run)
        service.run()


if __name__ == "__main__":
    main()
