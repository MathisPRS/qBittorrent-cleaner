# app/services/sonarr_service.py
import os
from typing import List, Dict, Optional
from ..repositories.torrents_repo import TorrentsRepo
from ..repositories.series_repo import SeriesRepo
from ..repositories.episodes_repo import EpisodesRepo
from ..adapters.qbittorrent_adapter import QbittorrentAdapter
from ..services.commun_service import CommunService
from ..extensions import db
from ..config import QBIT_HOST, QBIT_PASS, QBIT_USER
from app.logger import get_logger
from sqlalchemy.exc import SQLAlchemyError


class SonarrService:

    def __init__(self, app):
        self.app = app
        self.logger = get_logger(__name__, app=app)
        self.torrents_repo = TorrentsRepo()
        self.series_repo = SeriesRepo()
        self.episodes_repo = EpisodesRepo()
        self.qb_adapter = QbittorrentAdapter(QBIT_HOST, QBIT_USER, QBIT_PASS, logger_obj=self.logger)
        self.commun_service = CommunService(app)
        self._old_torrent_name: Optional[str] = None
        self._new_torrent_name: Optional[str] = None
        self._series_image_url: Optional[str] = None
        self._new_torrent = None

   
    def import_completed_episodes(self, dto: Dict) -> Dict:
        torrent_info = dto.get("torrent") or {}
        torrent_hash = torrent_info.get("hash")
        if not torrent_hash:
            raise ValueError("torrent hash required in dto['torrent']['hash']")

        sonarr_id = dto.get("sonarr_id")
        series_title = dto.get("title")
        self._series_image_url = dto.get("image")
        self._new_torrent_name = self.get_torrent_name(dto)

        # ensure torrent DB row exists
        torrent = self.commun_service.ensure_torrent_exists(torrent_hash, name=self._new_torrent_name)
        self._new_torrent = torrent

        # find series by sonarr_id (stored as string in Series.sonarr_id)
        existing_series = self.series_repo.get_by_sonarr_id(sonarr_id) if sonarr_id else None

        if existing_series is None:
            # create series + episodes
            return self.create_series_and_create_episodes(sonarr_id, series_title, torrent, dto)

        # series exists -> sync episodes
        return self.sync_existing_series_episodes(existing_series, torrent, dto)

   
    def get_torrent_name(self, dto: dict) -> str | None:
        release = dto.get("torrent")
        release_type = release.get("releaseType")

        if release_type == "seasonPack":
            source_path = release.get("sourcePath")
            if source_path:
                return os.path.basename(source_path.rstrip("/\\"))
            return None

        if release_type == "singleEpisode":
            return release.get("releaseTitle")

        return None
    
    # -----------------------------
    # Series not found flow
    # -----------------------------
    def create_series_and_create_episodes(self, sonarr_id: Optional[str], series_title: str, torrent, dto: Dict) -> Dict:
        created_series = self.series_repo.create(sonarr_id=sonarr_id, title=series_title)
        if not created_series:
            self.logger.error("Failed to create series (sonarr_id=%s title=%s)", sonarr_id, series_title)
            return {"action": "error", "message": "failed_create_series"}

        self.logger.info("create_series_and_create_episodes: created series id=%s sonarr_id=%s", created_series.id, sonarr_id)

        created_episodes = self.create_episodes_from_payload(created_series.id, torrent, dto.get("episodes", []))
        created_ids = [getattr(ep, "id", None) for ep in created_episodes]

        return {
            "action": "create_series_and_episodes",
            "series_id": created_series.id,
            "torrent_id": torrent.id,
            "created_episode_count": len(created_episodes),
            "created_episode_ids": created_ids
        }

    def create_episodes_from_payload(self, series_id: int, torrent, episodes_payload: List[Dict]) -> List[object]:
        created = []
        for e in episodes_payload:
            season_num = e.get("seasonNumber") or e.get("season") or 0
            episode_num = e.get("episodeNumber") or e.get("episode") or 0
            ep_title = e.get("title") or None
            try:
                ep = self.episodes_repo.create(
                    serie_id=series_id,
                    title=ep_title,
                    season=season_num,
                    episode=episode_num,
                    latest_torrent_id=torrent.id
                )
                if ep:
                    created.append(ep)
                    self.logger.info("create_episodes_from_payload: created episode S%02dE%02d id=%s", season_num, episode_num, getattr(ep, "id", None))
            except Exception:
                self.logger.exception("create_episodes_from_payload: failed to create S%02dE%02d for series_id=%s", season_num, episode_num, series_id)
                # continue to attempt remaining episodes
        return created

    # -----------------------------
    # Series exists flow
    # -----------------------------
    def sync_existing_series_episodes(self, series_obj, new_torrent, dto: Dict) -> Dict:
        """
        For each episode in DTO:
          - if episode not found -> create and mark created
          - if found and hash same -> noop
          - if found and hash different -> update latest_torrent_id, collect old hashes (including cross-seeds) for deletion
        After loop -> if hashes to delete exist: use CommunService to delete on qB and from DB and notify.
        """
        hashes_to_delete: List[str] = []
        updated_episodes: List[str] = []
        created_episodes: List[str] = []
        failed_episodes: List[str] = []

        self.logger.info("sync_existing_series_episodes: syncing series id=%s sonarr_id=%s", series_obj.id, series_obj.sonarr_id)

        for payload_ep in dto.get("episodes", []):
            season_num = payload_ep.get("seasonNumber") or payload_ep.get("season") or 0
            episode_num = payload_ep.get("episodeNumber") or payload_ep.get("episode") or 0
            ep_key = f"S{season_num:02d}E{episode_num:02d}"

            try:
                result = self.process_single_episode(series_obj, season_num, episode_num, payload_ep, new_torrent)
            except Exception:
                self.logger.exception("sync_existing_series_episodes: unexpected error processing episode %s for series_id=%s", ep_key, series_obj.id)
                failed_episodes.append(ep_key)
                continue

            # result is a dict with action and possibly hashes_to_add
            action = result.get("action")
            if action == "created":
                created_episodes.append(ep_key)
            elif action == "updated":
                updated_episodes.append(ep_key)
                # collect any returned old hashes to delete
                old_hashes = result.get("hashes_to_delete") or []
                for h in old_hashes:
                    nh = (h or "").strip().lower()
                    if nh and nh not in hashes_to_delete:
                        hashes_to_delete.append(nh)
            elif action == "same":
                # nothing to do
                pass
            else:
                # error or unknown
                if action == "error":
                    failed_episodes.append(ep_key)

        # After processing all episodes
        if not hashes_to_delete:
            # nothing to delete — notify and return
            self.logger.info("No deletion detected, no Gotify needed")
            return {
                "action": "sync_completed_no_deletes",
                "series_id": series_obj.id,
                "updated_episodes": updated_episodes,
                "created_episodes": created_episodes,
                "failed_episodes": failed_episodes
            }

        # If hashes to delete -> perform qB deletion and DB deletion using CommunService
        qb_out = self.commun_service.perform_qbittorrent_delete(hashes_to_delete)
        # qb_out: {deleted, failed, absent, hashes_to_delete_in_db}
        deleted = qb_out.get("deleted", []) or []
        failed = qb_out.get("failed", []) or []
        absent = qb_out.get("absent", []) or []
        hashes_for_db = qb_out.get("hashes_to_delete_in_db", [])

        bdd_result = self.commun_service.perform_bdd_delete(hashes_for_db)

        # prepare notification lists
        deleted_names = [n for (_h, n) in deleted if n]
        absent_names = list(absent) if absent else []
        failed_names = [n for (_h, n) in failed if n]

        # send notification using common service helper
        self.commun_service._send_notify(
            series_title := series_obj.title,
            old_torrent := self._old_torrent_name,
            new_torrent := self._new_torrent_name,
            deleted := deleted_names,
            not_found := created_episodes,
            failed := failed_names,
            image_url := self._series_image_url
        )

        return {
            "action": "replace_and_cleanup",
            "series_id": series_obj.id,
            "new_torrent_id": self._new_torrent.id,
            "deleted_db_rows": bdd_result.get("deleted_total", 0),
            "deleted_episodes": updated_episodes,
            "created_episodes": created_episodes,
            "failed_episodes": failed_episodes
        }

    # -----------------------------
    # Per-episode processor
    # -----------------------------
    def process_single_episode(self, series_obj, season: int, episode_num: int, payload_ep: Dict, new_torrent) -> Dict:
        """
        Process one episode payload:
         - If episode not found -> create with latest_torrent_id = new_torrent.id
         - If found:
             - if current latest_torrent_id -> same hash => noop
             - else -> update latest_torrent_id, return old hashes (old + its cross-seeds) to delete
        Returns a dict with 'action' and optional 'hashes_to_delete' list.
        """
        ep_identifier = f"S{season:02d}E{episode_num:02d}"
        existing = None
        try:
            existing = self.episodes_repo.get_by_series_season_episode(series_obj.id, season, episode_num)
        except Exception:
            self.logger.exception("process_single_episode: DB error while getting episode %s for series_id=%s", ep_identifier, series_obj.id)
            return {"action": "error"}

        if existing is None:
            # episode not in DB -> create
            try:
                created = self.episodes_repo.create(
                    serie_id=series_obj.id,
                    title=payload_ep.get("title"),
                    season=season,
                    episode=episode_num,
                    latest_torrent_id=new_torrent.id
                )
                if created:
                    self.logger.info("process_single_episode: created episode %s for series_id=%s with torrent_id=%s", ep_identifier, series_obj.id, new_torrent.id)
                    return {"action": "created"}
                else:
                    self.logger.error("process_single_episode: create returned falsy for %s", ep_identifier)
                    return {"action": "error"}
            except Exception:
                self.logger.exception("process_single_episode: failed to create episode %s", ep_identifier)
                return {"action": "error"}

        # episode exists -> check current latest torrent hash
        current_hash = None
        if existing.latest_torrent_id:
            cur_t = self.torrents_repo.get_by_id(existing.latest_torrent_id)
            if cur_t:
                current_hash = getattr(cur_t, "hash", None)
                # store for notification preview (most recent overwritten)
                self._old_torrent_name = getattr(cur_t, "name", None)

        # if same hash -> noop
        if current_hash and current_hash.lower() == new_torrent.hash.lower():
            self.logger.debug("process_single_episode: episode %s unchanged (hash match)", ep_identifier)
            return {"action": "same"}

        # else -> update episode.latest_torrent_id to new_torrent.id and collect old hashes
        old_torrent_id = existing.latest_torrent_id
        existing.latest_torrent_id = new_torrent.id
        try:
            db.session.add(existing)
            db.session.commit()
            self.logger.info("process_single_episode: updated episode %s to new torrent id=%s", ep_identifier, new_torrent.id)
        except Exception:
            self.logger.exception("process_single_episode: DB commit failed when updating episode %s", ep_identifier)
            try:
                db.session.rollback()
            except Exception:
                self.logger.exception("process_single_episode: rollback failed after commit error")
            return {"action": "error"}

        hashes_to_delete: List[str] = []
        if old_torrent_id:
            try:
                old_hashes = self.torrents_repo.find_hashes_to_delete(old_torrent_id)
                for h in old_hashes:
                    nh = (h or "").strip().lower()
                    if nh and nh not in hashes_to_delete:
                        hashes_to_delete.append(nh)
            except Exception:
                self.logger.exception("process_single_episode: failed to collect hashes to delete for old_torrent_id=%s", old_torrent_id)

        return {"action": "updated", "hashes_to_delete": hashes_to_delete}

