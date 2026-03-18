# app/services/ingest_service.py
"""
IngestService
=============
Responsible for persisting into the database torrents that were found
in qBittorrent but are absent from the DB.

Handles three cases:
  1. Movie torrent  → ensure Torrent row + Movie row + link
  2. Series torrent → ensure Torrent row + Series row + Episode rows + links
  3. Cross-seed     → ensure Torrent row (child) + link to parent Torrent row

Each method is idempotent: if a row already exists it is left untouched
(only missing rows are created).
"""
from typing import Dict, List, Optional

from app.logger import get_logger
from app.repositories.torrents_repo import TorrentsRepo
from app.repositories.series_repo import SeriesRepo
from app.repositories.episodes_repo import EpisodesRepo
from app.repositories.movies_repo import MoviesRepo
from app.adapters.qbittorrent_adapter import QbittorrentAdapter


class IngestService:

    def __init__(self, app):
        self.app = app
        self.logger = get_logger(__name__, app=app)
        self.torrents_repo = TorrentsRepo()
        self.series_repo = SeriesRepo()
        self.episodes_repo = EpisodesRepo()
        self.movies_repo = MoviesRepo()
        self.qb = QbittorrentAdapter()

    # ================================================================
    # PUBLIC: MOVIE
    # ================================================================

    def ingest_movie(self, torrent_hash: str, torrent_name: str, resolution: Dict) -> Dict:
        """
        Persist a movie torrent.

        resolution must be a dict with at least:
          - radarr_id   (str)
          - radarr_title (str)
        """
        radarr_id = resolution.get("radarr_id")
        radarr_title = resolution.get("radarr_title") or resolution.get("title") or torrent_name

        self.logger.info("[Ingest] Movie: hash=%s radarr_id=%s title=%s",
                         torrent_hash, radarr_id, radarr_title)

        # 1) Ensure torrent row exists
        torrent = self._ensure_torrent(torrent_hash, torrent_name)
        if not torrent:
            return {"ok": False, "reason": "torrent_creation_failed", "hash": torrent_hash}

        # 2) Ensure Movie row exists
        movie = self.movies_repo.get_by_radarr_id(radarr_id)

        if movie is None:
            movie = self.movies_repo.create(
                radarr_id=radarr_id,
                title=radarr_title,
                latest_torrent_id=torrent.id,
            )
            if not movie:
                return {"ok": False, "reason": "movie_creation_failed", "hash": torrent_hash}
            self.logger.info("[Ingest] Created Movie id=%s radarr_id=%s linked to torrent_id=%s",
                             movie.id, radarr_id, torrent.id)
            return {"ok": True, "action": "created", "movie_id": movie.id, "torrent_id": torrent.id}

        # Movie exists: only update latest_torrent_id if currently unset
        if movie.latest_torrent_id is None:
            self.movies_repo.update_latest_torrent_id(radarr_id, torrent.id)
            self.logger.info("[Ingest] Linked existing Movie id=%s to torrent_id=%s", movie.id, torrent.id)
            return {"ok": True, "action": "linked", "movie_id": movie.id, "torrent_id": torrent.id}

        self.logger.info("[Ingest] Movie id=%s already has torrent_id=%s, skipping",
                         movie.id, movie.latest_torrent_id)
        return {"ok": True, "action": "skipped", "movie_id": movie.id, "torrent_id": torrent.id}

    # ================================================================
    # PUBLIC: SERIES / EPISODES
    # ================================================================

    def ingest_series(self, torrent_hash: str, torrent_name: str, resolution: Dict) -> Dict:
        """
        Persist a series torrent.

        resolution must be a dict with at least:
          - sonarr_id    (str)
          - sonarr_title (str)
          - episodes     (list[dict]) — formatted Sonarr episode dicts
        """
        sonarr_id = resolution.get("sonarr_id")
        sonarr_title = resolution.get("sonarr_title") or resolution.get("title") or torrent_name
        episodes_payload: List[dict] = resolution.get("episodes") or []

        self.logger.info("[Ingest] Series: hash=%s sonarr_id=%s title=%s episodes=%d",
                         torrent_hash, sonarr_id, sonarr_title, len(episodes_payload))

        # 1) Ensure torrent row exists
        torrent = self._ensure_torrent(torrent_hash, torrent_name)
        if not torrent:
            return {"ok": False, "reason": "torrent_creation_failed", "hash": torrent_hash}

        # 2) Ensure Series row exists
        series = self.series_repo.get_by_sonarr_id(sonarr_id)
        if series is None:
            series = self.series_repo.create(sonarr_id=sonarr_id, title=sonarr_title)
            if not series:
                return {"ok": False, "reason": "series_creation_failed", "hash": torrent_hash}
            self.logger.info("[Ingest] Created Series id=%s sonarr_id=%s", series.id, sonarr_id)

        # 3) Upsert episodes
        created_episodes: List[str] = []
        skipped_episodes: List[str] = []
        failed_episodes: List[str] = []

        for ep in episodes_payload:
            season_num = ep.get("seasonNumber")
            episode_num = ep.get("episodeNumber")
            ep_title = ep.get("title")

            if season_num is None or episode_num is None:
                self.logger.warning("[Ingest] Episode missing season/episode numbers: %s", ep)
                failed_episodes.append("?")
                continue

            ep_key = f"S{season_num:02d}E{episode_num:02d}"

            try:
                existing = self.episodes_repo.get_by_series_season_episode(
                    series.id, season_num, episode_num
                )

                if existing is None:
                    # Create new episode linked to this torrent
                    created = self.episodes_repo.create(
                        serie_id=series.id,
                        title=ep_title,
                        season=season_num,
                        episode=episode_num,
                        latest_torrent_id=torrent.id,
                    )
                    if created:
                        created_episodes.append(ep_key)
                        self.logger.info("[Ingest] Created episode %s for series_id=%s torrent_id=%s",
                                         ep_key, series.id, torrent.id)
                    else:
                        failed_episodes.append(ep_key)
                else:
                    # Episode exists: only assign torrent if it has none
                    if existing.latest_torrent_id is None:
                        self.episodes_repo.update_latest_torrent_id(existing.id, torrent.id)
                        self.logger.info("[Ingest] Linked episode %s (id=%s) to torrent_id=%s",
                                         ep_key, existing.id, torrent.id)
                        created_episodes.append(ep_key)
                    else:
                        skipped_episodes.append(ep_key)

            except Exception:
                self.logger.exception("[Ingest] Unexpected error processing episode %s series_id=%s",
                                      ep_key, series.id)
                failed_episodes.append(ep_key)

        return {
            "ok": True,
            "series_id": series.id,
            "torrent_id": torrent.id,
            "created_episodes": created_episodes,
            "skipped_episodes": skipped_episodes,
            "failed_episodes": failed_episodes,
        }

    # ================================================================
    # PUBLIC: CROSS-SEED
    # ================================================================

    def ingest_cross_seed(self, torrent_hash: str, torrent_name: str) -> Dict:
        """
        Persist a cross-seed torrent.

        Looks up an existing parent torrent by name (same strategy as
        TorrentService.import_cross_seed) and links child to parent.
        Returns a result dict describing what happened.
        """
        self.logger.info("[Ingest] Cross-seed: hash=%s name=%s", torrent_hash, torrent_name)

        # 1) Look for a parent by name (no parent_hash available during audit)
        parent = None
        try:
            parent = self.torrents_repo.get_parent_by_name(name=torrent_name, parent_hash=None)
        except Exception:
            self.logger.exception("[Ingest] get_parent_by_name failed for name=%s", torrent_name)

        if parent is None:
            self.logger.warning("[Ingest] Cross-seed parent NOT found for name=%s hash=%s — skipping",
                                torrent_name, torrent_hash)
            return {
                "ok": False,
                "reason": "parent_not_found",
                "hash": torrent_hash,
                "name": torrent_name,
            }

        # 2) Ensure the child torrent row exists
        indexer = None
        try:
            indexer = self.qb.get_indexer_from_hash(torrent_hash)
        except Exception:
            self.logger.debug("[Ingest] Could not determine indexer for hash=%s", torrent_hash)

        child = self.torrents_repo.get_by_hash(torrent_hash)
        if child is None:
            child = self.torrents_repo.create(
                hashval=torrent_hash,
                name=torrent_name,
                indexer=indexer,
            )
            if not child:
                return {"ok": False, "reason": "child_creation_failed", "hash": torrent_hash}

        # 3) Link child → parent
        linked = self.torrents_repo.set_cross_seed_parent(
            child_hash=torrent_hash,
            parent_id=parent.id,
            child_name=torrent_name,
        )
        if linked:
            self.logger.info("[Ingest] Cross-seed linked: child_hash=%s parent_id=%s parent_hash=%s",
                             torrent_hash, parent.id, parent.hash)
            return {
                "ok": True,
                "action": "linked",
                "child_torrent_id": child.id,
                "parent_torrent_id": parent.id,
            }

        self.logger.warning("[Ingest] Cross-seed link failed for child_hash=%s parent_id=%s",
                            torrent_hash, parent.id)
        return {
            "ok": False,
            "reason": "link_failed",
            "hash": torrent_hash,
            "parent_id": parent.id,
        }

    # ================================================================
    # PRIVATE HELPERS
    # ================================================================

    def _ensure_torrent(self, torrent_hash: str, torrent_name: str):
        """
        Return existing torrent row or create a new one.
        Also looks up the indexer from qBittorrent tracker info.
        """
        existing = self.torrents_repo.get_by_hash(torrent_hash)
        if existing:
            return existing

        indexer = None
        try:
            indexer = self.qb.get_indexer_from_hash(torrent_hash)
        except Exception:
            self.logger.debug("[Ingest] Could not determine indexer for hash=%s", torrent_hash)

        torrent = self.torrents_repo.create(
            hashval=torrent_hash,
            name=torrent_name,
            indexer=indexer,
        )
        return torrent
