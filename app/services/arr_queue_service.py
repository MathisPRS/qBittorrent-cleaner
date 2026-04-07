# app/services/arr_queue_service.py
"""
ArrQueueService
===============
Fetches the set of torrent hashes currently managed by Radarr and Sonarr
via their respective download queues.

"Managed" means the *arr app is actively tracking the torrent — regardless of
its status (downloading, pending import, awaiting manual import, delayed,
failed, etc.).

This service is used by audit tasks to avoid touching torrents that are known
to the *arr stack but not yet written to the local DB (e.g. a torrent waiting
for a manual import interaction).
"""

from typing import Set

from app.adapters.radarr_adapter import RadarrAdapter
from app.adapters.sonarr_adapter import SonarrAdapter
from app.logger import get_logger


class ArrQueueService:
    """
    Aggregates download hashes tracked by Radarr and Sonarr queues.

    Usage:
        service = ArrQueueService()
        managed = service.get_managed_hashes()   # set of lowercase hashes
        if torrent_hash in managed:
            # skip — arr is handling it
    """

    def __init__(self):
        self.radarr = RadarrAdapter()
        self.sonarr = SonarrAdapter()
        self.logger = get_logger(__name__)

    # ----------------------------------------------------------------
    # Public API
    # ----------------------------------------------------------------

    def get_managed_hashes(self) -> Set[str]:
        """
        Returns the union of all torrent hashes present in the Radarr queue
        and the Sonarr queue.

        Failures on either side are logged and silently ignored so that a
        temporary *arr outage does not block the entire audit.
        """
        managed: Set[str] = set()
        managed.update(self._fetch_radarr_queue_hashes())
        managed.update(self._fetch_sonarr_queue_hashes())

        self.logger.info(
            "[ArrQueue] managed hashes fetched: total=%d", len(managed)
        )
        return managed

    # ----------------------------------------------------------------
    # Private helpers
    # ----------------------------------------------------------------

    def _fetch_radarr_queue_hashes(self) -> Set[str]:
        hashes: Set[str] = set()
        try:
            records = self.radarr.get_queue()
            for record in records:
                download_id = (record.get("downloadId") or "").strip().lower()
                if download_id:
                    hashes.add(download_id)
            self.logger.debug("[ArrQueue] Radarr queue hashes: %d", len(hashes))
        except Exception:
            self.logger.exception(
                "[ArrQueue] Failed to fetch Radarr queue — Radarr managed hashes skipped"
            )
        return hashes

    def _fetch_sonarr_queue_hashes(self) -> Set[str]:
        hashes: Set[str] = set()
        try:
            records = self.sonarr.get_queue()
            for record in records:
                download_id = (record.get("downloadId") or "").strip().lower()
                if download_id:
                    hashes.add(download_id)
            self.logger.debug("[ArrQueue] Sonarr queue hashes: %d", len(hashes))
        except Exception:
            self.logger.exception(
                "[ArrQueue] Failed to fetch Sonarr queue — Sonarr managed hashes skipped"
            )
        return hashes
