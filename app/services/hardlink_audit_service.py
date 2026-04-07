# app/services/hardlink_audit_service.py
"""
HardlinkAuditService
====================
Detects torrents in qBittorrent whose files are no longer hardlinked to the
media library.

Context
-------
When Radarr/Sonarr upgrades a file it:
  1. Downloads the new version and imports it → creates a new hardlink in /media
  2. Removes the old hardlink from /media (Radarr "manages" only its own copy)
  → The old torrent file left seeding in /downloads loses its /media counterpart.
  → Its hard link count (st_nlink) drops to 1: only the /downloads copy remains.

A torrent is considered orphaned when ALL of its files have st_nlink == 1,
meaning none of them are hardlinked anywhere outside /downloads.  Such a
torrent is no longer served to Jellyfin/Plex and can safely be queued for
deletion.

Guard: always cross-check with ArrQueueService before acting — a torrent
awaiting a manual import interaction also has st_nlink == 1 but must NOT be
deleted.
"""

import os
from typing import List, Set

from app.logger import get_logger


# qBittorrent state values that indicate the torrent is fully downloaded and
# seeding.  Torrents still downloading or in error state are skipped.
_SEEDING_STATES: Set[str] = {
    "uploading",
    "stalledUP",
    "queuedUP",
    "forcedUP",
    "seeding",
}

# Only audit media categories — other categories are out of scope.
_AUDITABLE_CATEGORIES: Set[str] = {"films", "series", "animes"}


class HardlinkAuditService:
    """
    Identifies seeding torrents whose files are no longer hardlinked to the
    media library (st_nlink == 1 on every file).

    Usage:
        service = HardlinkAuditService()
        orphaned = service.find_orphaned_hashes(qb_torrents, managed_hashes)
    """

    def __init__(self):
        self.logger = get_logger(__name__)

    # ----------------------------------------------------------------
    # Public API
    # ----------------------------------------------------------------

    def find_orphaned_hashes(
        self,
        qb_torrents: List[dict],
        managed_hashes: Set[str],
    ) -> List[str]:
        """
        Inspects each torrent in *qb_torrents* and returns the hashes of those
        that are fully orphaned and safe to queue for deletion.

        A torrent is orphaned when:
          - Its category is in _AUDITABLE_CATEGORIES
          - Its state is in _SEEDING_STATES (fully downloaded)
          - Its hash is NOT in *managed_hashes* (not awaiting arr action)
          - Every file under its content_path has st_nlink == 1

        Args:
            qb_torrents:    Output of QbittorrentAdapter.get_all_torrents().
                            Must include 'content_path', 'state', 'category'.
            managed_hashes: Hashes currently tracked by Radarr/Sonarr queues
                            (from ArrQueueService.get_managed_hashes()).

        Returns:
            List of lowercase torrent hashes that can be passed directly to
            DeferredDeletionService.filter_deferred_deletion_hash().
        """
        orphaned: List[str] = []

        for torrent in qb_torrents:
            hash_ = (torrent.get("hash") or "").strip().lower()
            if not hash_:
                continue

            category = (torrent.get("category") or "").strip().lower()
            if category not in _AUDITABLE_CATEGORIES:
                continue

            state = (torrent.get("state") or "").strip().lower()
            if state not in _SEEDING_STATES:
                self.logger.debug(
                    "[HardlinkAudit] skip hash=%s — state '%s' is not a seeding state",
                    hash_, state,
                )
                continue

            if hash_ in managed_hashes:
                self.logger.debug(
                    "[HardlinkAudit] skip hash=%s — currently tracked in arr queue",
                    hash_,
                )
                continue

            content_path = (torrent.get("content_path") or "").strip()
            if not content_path:
                self.logger.debug(
                    "[HardlinkAudit] skip hash=%s — content_path is empty", hash_
                )
                continue

            if not os.path.exists(content_path):
                self.logger.debug(
                    "[HardlinkAudit] skip hash=%s — content_path not accessible: %s",
                    hash_, content_path,
                )
                continue

            if self._is_orphaned(content_path):
                self.logger.info(
                    "[HardlinkAudit] orphaned torrent found: hash=%s name=%s path=%s",
                    hash_, torrent.get("name"), content_path,
                )
                orphaned.append(hash_)

        self.logger.info(
            "[HardlinkAudit] scan complete: checked=%d orphaned=%d",
            len(qb_torrents), len(orphaned),
        )
        return orphaned

    # ----------------------------------------------------------------
    # Private helpers
    # ----------------------------------------------------------------

    def _is_orphaned(self, content_path: str) -> bool:
        """
        Returns True if every regular file under *content_path* has a hard
        link count of exactly 1 (not linked anywhere outside /downloads).

        If even one file has st_nlink >= 2 the torrent still has an active
        hardlink and must NOT be deleted.

        On any unexpected filesystem error the method returns False so that
        the torrent is kept — safety over liveness.
        """
        try:
            if os.path.isfile(content_path):
                return self._get_link_count(content_path) == 1

            if os.path.isdir(content_path):
                file_paths = self._collect_files(content_path)
                if not file_paths:
                    # Empty directory — keep it to be safe
                    return False
                return all(self._get_link_count(fp) == 1 for fp in file_paths)

        except Exception:
            self.logger.exception(
                "[HardlinkAudit] _is_orphaned error for path=%s — treating as NOT orphaned",
                content_path,
            )

        return False

    def _get_link_count(self, file_path: str) -> int:
        """
        Returns the hard link count (st_nlink) for a single file.
        Returns 2 on error so the caller treats the file as still linked (safe default).
        """
        try:
            return os.stat(file_path).st_nlink
        except OSError:
            self.logger.warning(
                "[HardlinkAudit] cannot stat file=%s — assuming linked", file_path
            )
            return 2  # Safe default: do not delete if we cannot verify

    def _collect_files(self, directory: str) -> List[str]:
        """
        Recursively collects all regular file paths under *directory*.
        Symlinks are excluded — hardlink semantics do not apply to them.
        """
        files: List[str] = []
        try:
            for root, _dirs, filenames in os.walk(directory):
                for filename in filenames:
                    full_path = os.path.join(root, filename)
                    if os.path.isfile(full_path) and not os.path.islink(full_path):
                        files.append(full_path)
        except Exception:
            self.logger.exception(
                "[HardlinkAudit] _collect_files error for dir=%s", directory
            )
        return files
