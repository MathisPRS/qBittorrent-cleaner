# app/services/sonarr_service.py
from typing import List, Dict, Optional
from ..repositories.torrents_repo import TorrentsRepo
from ..repositories.series_repo import SeriesRepo
from ..repositories.episodes_repo import EpisodesRepo
from ..adapters.qbittorrent_adapter import QbittorrentAdapter
from ..adapters.gotify_adapter import notify_gotify
from ..extensions import db
from ..config import QBIT_HOST, QBIT_PASS, QBIT_USER
from app.logger import get_logger
from sqlalchemy.exc import SQLAlchemyError

class SonarrService:
    """
    Service for processing Sonarr 'Download' webhook payloads.
    Responsibilities split into clear functions:
      - ensure_torrent_exists
      - ensure_series_and_create_missing_episodes
      - sync_existing_series_episodes
      - collect_old_hashes_for_deletion
      - delete_hashes_on_qb_and_db
      - send_cleanup_notification
    """

    def __init__(self, app):
        self.app = app
        self.logger = get_logger(__name__, app=app)
        self.torrents = TorrentsRepo()
        self.series = SeriesRepo()
        self.episodes = EpisodesRepo()
        self.qb = QbittorrentAdapter(QBIT_HOST, QBIT_USER, QBIT_PASS, logger_obj=self.logger)
        self._old_torrent_name: Optional[str] = None
        self._new_torrent_name: Optional[str] = None
        self._series_image_url: Optional[str] = None

    # -----------------------------
    # Public entrypoint
    # -----------------------------
    def import_completed_episodes(self, dto: Dict) -> Dict:
        """
        High-level orchestrator for Sonarr import events.
        Returns a dict describing the performed action.
        """
        # defensive parsing
        torrent_info = dto.get("torrent") or {}
        torrent_hash = torrent_info.get("hash")
        if not torrent_hash:
            raise ValueError("torrent hash required in dto['torrent']['hash']")

        sonarr_id = dto.get("sonarr_id")
        series_title = dto.get("title")
        self._series_image_url = dto.get("image")
        self._new_torrent_name = torrent_info.get("releaseTitle") or None

        # Ensure torrent record exists (create if missing)
        torrent = self.ensure_torrent_exists(torrent_hash, name=self._new_torrent_name)

        # Find series by sonarr_id (stringified in repo), if none => create + episodes
        existing_series = self.series.get_by_sonarr_id(sonarr_id) if sonarr_id else None

        if existing_series is None:
            return self._handle_series_not_found(sonarr_id, series_title, torrent, dto)

        # Otherwise series exists: sync episodes one-by-one
        return self._handle_series_exists(existing_series, torrent, dto)

  
    def ensure_torrent_exists(self, torrent_hash: str, name: Optional[str] = None):
        t = self.torrents.get_by_hash(torrent_hash)
        if t:
            self.logger.debug("ensure_torrent_exists: found existing torrent id=%s hash=%s", t.id, t.hash)
            return t
        self.logger.info("ensure_torrent_exists: creating torrent hash=%s name=%s", torrent_hash, name)
        return self.torrents.create(hashval=torrent_hash, name=name)


    def _handle_series_not_found(self, sonarr_id: str, title: str, torrent, dto: Dict) -> Dict:
        
        created_series = self.series.create(sonarr_id=sonarr_id, title=title)
        self.logger.info("Created series id=%s sonarr_id=%s", created_series.id, sonarr_id)

        created_episode_ids = []
        for e in dto.get("episodes", []):
            season_num = e.get("seasonNumber") or e.get("season") or 0
            episode_num = e.get("episodeNumber") or e.get("episode") or 0
            ep_title = e.get("title")
            try:
                ep = self.episodes.create(
                    serie_id=created_series.id,
                    title=ep_title,
                    season=season_num,
                    episode=episode_num,
                    latest_torrent_id=torrent.id
                )
                created_episode_ids.append(f"S{season_num:02d}E{episode_num:02d}")
            except Exception:
                self.logger.exception("Failed to create episode S%sE%s for new series id=%s", season_num, episode_num, created_series.id)
                # continue creating other episodes

        return {
            "action": "create_series_and_episodes",
            "series_id": created_series.id,
            "torrent_id": torrent.id,
            "created_episodes": created_episode_ids
        }

    def _handle_series_exists(self, series_obj, new_torrent, dto: Dict) -> Dict:
        
        hashes_to_delete: List[str] = []
        updated_episode_identifiers: List[str] = []
        created_episode_identifiers: List[str] = []
        failed_updates: List[str] = []

        self.logger.info("Syncing episodes for series id=%s sonarr_id=%s", series_obj.id, series_obj.sonarr_id)

        for payload_episode in dto.get("episodes", []):
            season_num = payload_episode.get("seasonNumber") or payload_episode.get("season") or 0
            episode_num = payload_episode.get("episodeNumber") or payload_episode.get("episode") or 0
            ep_identifier = f"{series_obj.id}|S{season_num:02d}E{episode_num:02d}"

            try:
                existing_episode = self.episodes.get_by_series_season_episode(series_obj.id, season_num, episode_num)
            except Exception:
                self.logger.exception("DB error while fetching episode %s", ep_identifier)
                failed_updates.append(ep_identifier)
                continue

            match existing_episode:
                case None:
                    # create missing episode linked to the new torrent
                    try:
                        self.episodes.create(
                            serie_id=series_obj.id,
                            title=payload_episode.get("title"),
                            season=season_num,
                            episode=episode_num,
                            latest_torrent_id=new_torrent.id
                        )
                        created_episode_identifiers.append(ep_identifier)
                        self.logger.info("Created missing episode %s", ep_identifier)
                    except Exception:
                        self.logger.exception("Failed to create missing episode %s", ep_identifier)
                        failed_updates.append(ep_identifier)
                case _:
                    # Episode exists — compare current latest torrent
                    try:
                        current_torrent_hash = None
                        if existing_episode.latest_torrent_id:
                            current_torrent = self.torrents.get_by_id(existing_episode.latest_torrent_id)
                            if current_torrent:
                                current_torrent_hash = getattr(current_torrent, "hash", None)
                                # keep name for notification (last seen)
                                self._old_torrent_name = getattr(current_torrent, "name", None)
                        # if same hash -> nothing to do
                        if current_torrent_hash and current_torrent_hash.lower() == new_torrent.hash.lower():
                            self.logger.debug("Episode %s unchanged (hash %s)", ep_identifier, new_torrent.hash)
                            continue

                        # otherwise update episode.latest_torrent_id -> new_torrent
                        old_torrent_id = existing_episode.latest_torrent_id
                        existing_episode.latest_torrent_id = new_torrent.id
                        try:
                            db.session.add(existing_episode)
                            db.session.commit()
                            updated_episode_identifiers.append(ep_identifier)
                            self.logger.info("Updated episode %s to new torrent id=%s", ep_identifier, new_torrent.id)
                        except Exception:
                            self.logger.exception("Failed to commit update for episode %s", ep_identifier)
                            try:
                                db.session.rollback()
                            except Exception:
                                self.logger.exception("Rollback failed after episode update failure")
                            failed_updates.append(ep_identifier)
                            continue

                        # collect hashes (old + cross-seeds) for deletion
                        if old_torrent_id:
                            try:
                                old_hashes = self.torrents.find_hashes_to_delete(old_torrent_id)
                                for h in old_hashes:
                                    nh = (h or "").strip().lower()
                                    if nh and nh not in hashes_to_delete:
                                        hashes_to_delete.append(nh)
                            except Exception:
                                self.logger.exception("Failed to collect hashes_to_delete for old_torrent_id=%s", old_torrent_id)
                    except Exception:
                        self.logger.exception("Unexpected error while processing episode %s", ep_identifier)
                        failed_updates.append(ep_identifier)
                        continue

        # end loop — decide next step
        if not hashes_to_delete:
            # nothing to delete -> simply report sync summary
            self.logger.info("No old hashes to delete for series id=%s", series_obj.id)
            # send a lightweight notification that sync was performed (optional)
            self.send_cleanup_notification(
                series_title=series_obj.title,
                old_torrent=self._old_torrent_name,
                new_torrent=self._new_torrent_name,
                deleted=[],
                created=created_episode_identifiers,
                failed=failed_updates,
                image_url=self._series_image_url
            )
            return {
                "action": "sync_completed_no_deletes",
                "series_id": series_obj.id,
                "updated_episodes": updated_episode_identifiers,
                "created_episodes": created_episode_identifiers,
                "failed_episodes": failed_updates
            }

        # if we have hashes to delete -> delete on qBittorrent and then from DB
        qb_result = self.delete_hashes_on_qb_and_db(hashes_to_delete)

        # prepare arrays for notification
        deleted_rows_count = qb_result.get("bdd_deleted_total", 0)
        deleted_names = qb_result.get("deleted_names", [])
        absent_names = qb_result.get("absent_names", [])
        failed_names = qb_result.get("failed_names", [])

        self.send_cleanup_notification(
            series_title=series_obj.title,
            old_torrent=self._old_torrent_name,
            new_torrent=self._new_torrent_name,
            deleted=deleted_names,
            created=created_episode_identifiers,
            failed=failed_names,
            image_url=self._series_image_url,
            absent=absent_names
        )

        return {
            "action": "replace_and_cleanup",
            "series_id": series_obj.id,
            "new_torrent_id": new_torrent.id,
            "deleted_db_rows": deleted_rows_count,
            "deleted_episodes": updated_episode_identifiers,
            "created_episodes": created_episode_identifiers,
            "failed_episodes": failed_updates
        }

   
    def delete_hashes_on_qb_and_db(self, hashes: List[str]) -> Dict:
        """
        Given a list of normalized hashes, call qBittorrent deletion and then delete rows from DB.
        Returns a summary dict with deleted/absent/failed lists and bdd deletion stats.
        """
        if not hashes:
            return {"deleted_names": [], "absent_names": [], "failed_names": [], "bdd_deleted_total": 0}

        # call qB adapter
        qb_result = self.qb.delete_torrents(hashes, delete_files=True)
        deleted = qb_result.get("deleted", []) or []
        failed = qb_result.get("failed", []) or []
        absent = qb_result.get("absent", []) or []

        # names for notification
        deleted_names = [name for (_hash, name) in deleted if name]
        failed_names = [name for (_hash, name) in failed if name]
        absent_names = list(absent) if absent else []

        # prepare db deletion list: deleted_hashes + absent
        deleted_hashes = [h for (h, _n) in deleted]
        hashes_to_delete_in_db = deleted_hashes + absent_names

        # delete from DB using torrent repo (reuse its delete_by_hash)
        bdd_deletion_summary = {"deleted_total": 0, "deleted_hashes": [], "skipped_hashes": []}
        try:
            # normalize lowercased unique list
            normalized = []
            seen = set()
            for h in hashes_to_delete_in_db:
                nh = (h or "").strip().lower()
                if nh and nh not in seen:
                    seen.add(nh)
                    normalized.append(nh)

            for nh in normalized:
                try:
                    rows_deleted = self.torrents.delete_by_hash(nh)
                    if rows_deleted:
                        bdd_deletion_summary["deleted_hashes"].append(nh)
                        self.logger.info("[BBDD] removed torrent hash=%s rows=%d", nh, rows_deleted)
                    else:
                        bdd_deletion_summary["skipped_hashes"].append(nh)
                        self.logger.info("[BBDD] nothing to remove for hash=%s", nh)
                except Exception:
                    self.logger.exception("[BBDD] failed deleting hash=%s", nh)
                    bdd_deletion_summary["skipped_hashes"].append(nh)

            bdd_deletion_summary["deleted_total"] = len(bdd_deletion_summary["deleted_hashes"])
            try:
                db.session.commit()
            except Exception:
                self.logger.exception("[BBDD] commit failed after deletions, rolling back")
                try:
                    db.session.rollback()
                except Exception:
                    self.logger.exception("[BBDD] rollback failed")
                # consider whole operation failed from DB perspective
                bdd_deletion_summary = {"deleted_total": 0, "deleted_hashes": [], "skipped_hashes": normalized}
        except SQLAlchemyError:
            self.logger.exception("[BBDD] SQLAlchemyError during bulk delete; rolling back")
            try:
                db.session.rollback()
            except Exception:
                self.logger.exception("[BBDD] rollback failed after SQLAlchemyError")
            bdd_deletion_summary = {"deleted_total": 0, "deleted_hashes": [], "skipped_hashes": []}

        return {
            "deleted_names": deleted_names,
            "absent_names": absent_names,
            "failed_names": failed_names,
            "bdd_deleted_total": bdd_deletion_summary["deleted_total"]
        }

    # -----------------------------
    # Notification
    # -----------------------------
    def send_cleanup_notification(
            self,
            series_title: str,
            old_torrent: Optional[str],
            new_torrent: Optional[str],
            deleted: List[str],
            created: List[str],
            failed: List[str],
            image_url: Optional[str] = None,
            absent: Optional[List[str]] = None
        ) -> Dict:
        """
        Build and send a Gotify notification summarizing the cleanup result.
        """
        absent = absent or []
        deleted = deleted or []
        created = created or []
        failed = failed or []

        # Title decision using boolean tuple (deleted, created, failed)
        title_map = {
            (True, False, False): "Webhook Cleaner : Nettoyage effectué",
            (False, True, False): "Webhook Cleaner : Création effectuée",
            (True, True, False): "Webhook Cleaner : Nettoyage et création effectués",
            (False, False, True): "Webhook Cleaner : Échec du nettoyage",
            (True, False, True): "Webhook Cleaner : Nettoyage partiel",
            (False, True, True): "Webhook Cleaner : Création partielle",
            (True, True, True): "Webhook Cleaner : Nettoyage partiel avec erreurs"
        }
        title = title_map.get((bool(deleted), bool(created), bool(failed)), "Webhook Cleaner : État inconnu")

        lines: List[str] = []
        if old_torrent:
            lines.append(f"Old: {old_torrent}")
        if new_torrent:
            lines.append(f"New: {new_torrent}")
        if deleted:
            lines.append("Deleted: " + ", ".join(deleted)[:1000])
        if created:
            lines.append("Created episodes: " + ", ".join(created))
        if absent:
            lines.append("Absent on qB: " + ", ".join(absent))
        if failed:
            lines.append("Failed: " + ", ".join(failed))
        if image_url:
            lines.append("Image: " + image_url)

        preview = (lines[0] + " | " + (lines[1] if len(lines) > 1 else ""))[:300] if lines else ""
        self.logger.info("[Gotify] title=%s preview=%s", title, preview)
        self.logger.debug("[Gotify] full message lines: %s", lines)

        return notify_gotify(title, lines, image_url=image_url)
