# app/services/sonarr_service.py
from typing import List, Dict, Optional
from ..repositories.torrents_repo import TorrentsRepo
from ..repositories.series_repo import SeriesRepo
from ..repositories.episodes_repo import EpisodesRepo
from ..adapters.qbittorrent_adapter import QbittorrentAdapter
from .commun_services import CommunService
from app.services.deferred_deletions_services import DeferredDeletionService
from app.logger import get_logger


class SonarrService:
    def __init__(self, app):
        self.app = app
        self.logger = get_logger(__name__, app=app)
        self.torrents_repo = TorrentsRepo()
        self.series_repo = SeriesRepo()
        self.episodes_repo = EpisodesRepo()
        self.qb_adapter = QbittorrentAdapter()
        self.commun_service = CommunService(app)
        self.deferred_deletion_services = DeferredDeletionService(app)

    def import_completed_episodes(self, dto: Dict) -> Dict:
        torrent_info = dto.get("torrent")
        if not torrent_info or "hash" not in torrent_info:
            raise ValueError("torrent hash required in dto['torrent']['hash']")

        torrent_hash = torrent_info["hash"]
        sonarr_id = dto.get("sonarr_id")
        if not sonarr_id:
            self.logger.warning(
                "import_completed_episodes: no sonarr_id — refusing to create orphan torrent/series (hash=%s)",
                torrent_hash,
            )
            return {"action": "skipped", "reason": "no_sonarr_id"}

        series_title = dto.get("title")
        series_image_url = dto.get("image")
        new_torrent_name = self.commun_service.get_torrent_name_from_json(dto)

        # Ensure torrent DB row exists (and returns torrent object with id/hash/name)
        torrent = self.commun_service.ensure_torrent_exists(torrent_hash, name=new_torrent_name)

        # find series by sonarr_id (stored as string in Series.sonarr_id)
        existing_series = self.series_repo.get_by_sonarr_id(sonarr_id) if sonarr_id else None
        if existing_series is None:
            return self.create_series_and_create_episodes(sonarr_id, series_title, torrent, dto)

        return self.update_existing_series_episodes(
            existing_series, torrent, dto,
            new_torrent_name=new_torrent_name,
            series_image_url=series_image_url,
        )


    def create_series_and_create_episodes(self, sonarr_id: Optional[str], series_title: str, torrent, dto: Dict) -> Dict:
        created_series = self.series_repo.create(sonarr_id=sonarr_id, title=series_title)
        if not created_series:
            self.logger.error(
                "create_series_and_create_episodes: failed to create series (sonarr_id=%s title=%s)",
                sonarr_id, series_title
            )
            return {"action": "error", "message": "failed_create_series"}

        self.logger.info(
            "create_series_and_create_episodes: created series id=%s sonarr_id=%s",
            created_series.id, sonarr_id
        )

        episodes_payload = dto.get("episodes", [])
        created_episodes = self.create_episodes_from_payload(created_series.id, torrent, episodes_payload)
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
            # defensive but concise extraction
            season_num = e.get("seasonNumber")
            episode_num = e.get("episodeNumber")
            ep_title = e.get("title")

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
                    self.logger.info(
                        "create_episodes_from_payload: created episode S%02dE%02d id=%s",
                        season_num, episode_num, getattr(ep, "id", None)
                    )
            except Exception:
                self.logger.exception(
                    "create_episodes_from_payload: failed to create S%02dE%02d for series_id=%s",
                    season_num, episode_num, series_id
                )

        return created


    def update_existing_series_episodes(
        self,
        series_obj,
        new_torrent,
        dto: Dict,
        new_torrent_name: Optional[str] = None,
        series_image_url: Optional[str] = None,
    ) -> Dict:
        hashes_to_delete: List[str] = []
        updated_episodes: List[str] = []
        created_episodes: List[str] = []
        failed_episodes: List[str] = []
        old_torrent_name: Optional[str] = None

        self.logger.info(
            "update_existing_series_episodes: syncing series id=%s sonarr_id=%s",
            series_obj.id, series_obj.sonarr_id
        )

        for payload_ep in dto.get("episodes", []):
            season_num = payload_ep.get("seasonNumber") or payload_ep.get("season") or 0
            episode_num = payload_ep.get("episodeNumber") or payload_ep.get("episode") or 0
            ep_key = f"S{season_num:02d}E{episode_num:02d}"

            try:
                result = self.process_single_episode(series_obj, season_num, episode_num, payload_ep, new_torrent)
            except Exception:
                self.logger.exception(
                    "update_existing_series_episodes: unexpected error processing episode %s for series_id=%s",
                    ep_key, series_obj.id
                )
                failed_episodes.append(ep_key)
                continue

            action = result.get("action")
            if action == "created":
                created_episodes.append(ep_key)
            elif action == "updated":
                updated_episodes.append(ep_key)
                # capture old_torrent_name from the first episode that had one
                if old_torrent_name is None:
                    old_torrent_name = result.get("old_torrent_name")
                old_hashes = result.get("hashes_to_delete", []) or []
                for h in old_hashes:
                    if not h:
                        continue
                    nh = h.strip().lower()
                    if nh and nh not in hashes_to_delete:
                        hashes_to_delete.append(nh)
            elif action == "same":
                pass
            else:
                if action == "error":
                    failed_episodes.append(ep_key)

        # After processing all episodes
        if not hashes_to_delete:
            self.logger.info("update_existing_series_episodes: No deletion detected, no Gotify needed")
            return {
                "action": "sync_completed_no_deletes",
                "series_id": series_obj.id,
                "updated_episodes": updated_episodes,
                "created_episodes": created_episodes,
                "failed_episodes": failed_episodes
            }

        # Partition ready vs deferred and enqueue deferred ones inside filter_deferred_deletion_hash
        try:
            ready_to_be_deleted = self.deferred_deletion_services.filter_deferred_deletion_hash(hashes_to_delete)
        except Exception:
            self.logger.exception("update_existing_series_episodes: filter_deferred_deletion_hash failed")
            # fallback conservative: attempt to delete everything
            ready_to_be_deleted = list(hashes_to_delete)

        if not ready_to_be_deleted:
            self.logger.info(
                "update_existing_series_episodes: no hashes ready for immediate deletion (all deferred for later cleanup)"
            )

            try:
                self.commun_service._send_notify(
                    series_obj.title,
                    old_torrent_name,
                    new_torrent_name,
                    deleted=[],            # nothing deleted now
                    not_found=created_episodes,
                    failed=[],
                    image_url=series_image_url
                )
            except Exception:
                self.logger.exception("update_existing_series_episodes: notify failed (non-blocking)")

            return {
                "action": "sync_completed_deferred",
                "series_id": series_obj.id,
                "updated_episodes": updated_episodes,
                "created_episodes": created_episodes,
                "failed_episodes": failed_episodes,
                "note": "all_hashes_deferred"
            }

        # Delete ready hashes and notify (single helper)
        return self.delete_ready_hashes_and_notify(
            ready_to_be_deleted, series_obj, new_torrent,
            updated_episodes, created_episodes, failed_episodes,
            old_torrent_name=old_torrent_name,
            new_torrent_name=new_torrent_name,
            series_image_url=series_image_url,
        )


    def process_single_episode(self, series_obj, season: int, episode_num: int, payload_ep: Dict, new_torrent) -> Dict:
        ep_identifier = f"S{season:02d}E{episode_num:02d}"

        try:
            episode = self.episodes_repo.get_by_series_season_episode(series_obj.id, season, episode_num)
        except Exception:
            self.logger.exception(
                "process_single_episode: DB error while getting episode %s for series_id=%s",
                ep_identifier, series_obj.id
            )
            return {"action": "error"}

        if episode is None:
            # create episode
            try:
                created = self.episodes_repo.create(
                    serie_id=series_obj.id,
                    title=payload_ep.get("title"),
                    season=season,
                    episode=episode_num,
                    latest_torrent_id=new_torrent.id
                )
                if created:
                    self.logger.info(
                        "process_single_episode: created episode %s for series_id=%s with torrent_id=%s",
                        ep_identifier, series_obj.id, new_torrent.id
                    )
                    return {"action": "created"}
                self.logger.error("process_single_episode: create returned falsy for %s", ep_identifier)
                return {"action": "error"}
            except Exception:
                self.logger.exception("process_single_episode: failed to create episode %s", ep_identifier)
                return {"action": "error"}

        # episode exists -> check current latest torrent hash
        current_hash = None
        old_torrent_name: Optional[str] = None
        if episode.latest_torrent_id:
            try:
                cur_t = self.torrents_repo.get_by_id(episode.latest_torrent_id)
                if cur_t:
                    current_hash = getattr(cur_t, "hash", None)
                    old_torrent_name = getattr(cur_t, "name", None)
            except Exception:
                self.logger.exception("process_single_episode: failed to load current torrent for episode %s", ep_identifier)

        new_hash = getattr(new_torrent, "hash", None)
        if current_hash and new_hash and current_hash.strip().lower() == new_hash.strip().lower():
            self.logger.debug("process_single_episode: episode %s unchanged (hash match)", ep_identifier)
            return {"action": "same"}

        # update latest_torrent_id to new torrent via repo (no direct db.session)
        old_torrent_id = episode.latest_torrent_id
        try:
            updated = self.episodes_repo.update_latest_torrent_id(episode.id, new_torrent.id)
            if not updated:
                self.logger.warning(
                    "process_single_episode: update affected 0 rows when updating episode id=%s", getattr(episode, "id", None)
                )
            else:
                self.logger.info("process_single_episode: updated episode %s to new torrent id=%s", ep_identifier, new_torrent.id)
        except Exception:
            self.logger.exception("process_single_episode: DB update failed when updating episode %s", ep_identifier)
            return {"action": "error"}

        # collect hashes to delete for old torrent id (old + cross-seeds)
        hashes_to_delete: List[str] = []
        if old_torrent_id:
            try:
                old_hashes = self.torrents_repo.get_hashes_to_delete(old_torrent_id)
                for h in old_hashes:
                    if not h:
                        continue
                    nh = h.strip().lower()
                    if nh and nh not in hashes_to_delete:
                        hashes_to_delete.append(nh)
            except Exception:
                self.logger.exception(
                    "process_single_episode: failed to collect hashes to delete for old_torrent_id=%s",
                    old_torrent_id
                )

        return {"action": "updated", "hashes_to_delete": hashes_to_delete, "old_torrent_name": old_torrent_name}


    def delete_ready_hashes_and_notify(
        self,
        ready_hashes: List[str],
        series_obj,
        new_torrent,
        updated_episodes: List[str],
        created_episodes: List[str],
        failed_episodes: List[str],
        old_torrent_name: Optional[str] = None,
        new_torrent_name: Optional[str] = None,
        series_image_url: Optional[str] = None,
    ) -> Dict:

        result = self.commun_service.perform_deletion(ready_hashes)

        # Résultats de perform_deletion (contrat)
        deleted_names = result["deleted_names"]
        absent_names = result["absent_names"]
        failed_names = result["failed_names"]
        deleted_db_rows = result["db_result"]["deleted_total"]

        try:
            self.commun_service._send_notify(
                series_obj.title,
                old_torrent_name,
                new_torrent_name,
                deleted_names,
                created_episodes,   # not_found / newly created episodes
                failed_names,
                series_image_url
            )
        except Exception:
            self.logger.exception("delete_ready_hashes_and_notify: notify failed (non-blocking)")

        return {
            "action": "replace_and_cleanup",
            "series_id": series_obj.id,
            "new_torrent_id": getattr(new_torrent, "id", None),
            "deleted_db_rows": deleted_db_rows,
            "deleted_episodes": updated_episodes,
            "created_episodes": created_episodes,
            "failed_episodes": failed_episodes
        }
