"""
Integration tests for SonarrService.import_completed_episodes.

Scenarios covered:

Movie side (series):
  Test 1 — Series and episodes do not exist          → created
  Test 2 — Series exists, episode exists, same hash  → sync_completed_no_deletes (no-op)
  Test 3 — Series exists, episode exists, new hash   → episode updated, old torrent deleted
  Test 4 — Series exists, some episodes new          → new episodes created, existing unchanged
  Test 5 — Multi-episode torrent, all updated        → all old torrents deleted

External I/O:
  - QbittorrentAdapter  → patched (delete_torrents reports all deleted)
  - notify_gotify       → already patched session-wide in conftest.py
  - DeferredDeletionService._clock → frozen far in past (nothing deferred)
"""
import uuid
import pytest
from unittest.mock import MagicMock

from tests.conftest import make_torrent, make_series, make_episode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unique() -> str:
    return uuid.uuid4().hex[:12]


def _build_service(app):
    """
    Build a SonarrService with controlled external dependencies.
    """
    from app.services.sonarr_services import SonarrService
    svc = SonarrService(app)

    def _fake_delete(hashes, delete_files=True):
        return {
            "deleted": [(h, h) for h in hashes],
            "failed": [],
            "absent": [],
        }

    svc.qb_adapter.get_indexer_from_hash = MagicMock(return_value="ygg")
    svc.qb_adapter.delete_torrents = MagicMock(side_effect=_fake_delete)
    svc.commun_service.qb.get_indexer_from_hash = MagicMock(return_value="ygg")
    svc.commun_service.qb.delete_torrents = MagicMock(side_effect=_fake_delete)

    # Bypass deferred logic entirely: all candidate hashes are immediately ready.
    # This avoids dependency on qBittorrent indexer lookups and Celery scheduling
    # in the test environment.
    svc.deferred_deletion_services.filter_deferred_deletion_hash = lambda hashes: list(hashes)

    return svc


def _ep(season: int, episode: int, title: str = None) -> dict:
    """Build a single episode payload dict as Sonarr would send."""
    return {
        "seasonNumber": season,
        "episodeNumber": episode,
        "title": title or f"Episode S{season:02d}E{episode:02d}",
    }


def _dto(hash_: str, name: str, sonarr_id: str, title: str, episodes: list) -> dict:
    return {
        "torrent": {"hash": hash_, "sourcePath": f"/data/{name}"},
        "sonarr_id": sonarr_id,
        "title": title,
        "image": None,
        "episodes": episodes,
    }


# ---------------------------------------------------------------------------
# Test 1 — Series and episodes do not exist
# ---------------------------------------------------------------------------

class TestSeriesNotInDB:
    def test_creates_series_torrent_and_episodes(self, app, db_session):
        """
        A completely unknown series must result in:
        - a new Torrent row
        - a new Series row
        - one Episode row per episode in the payload
        - action="create_series_and_episodes"
        """
        with app.app_context():
            from app.repositories.series_repo import SeriesRepo
            from app.repositories.episodes_repo import EpisodesRepo
            from app.repositories.torrents_repo import TorrentsRepo

            sonarr_id = _unique()
            hash_ = _unique()
            title = f"New Series {sonarr_id}"
            episodes_payload = [_ep(1, 1, "Pilot"), _ep(1, 2, "Second")]

            svc = _build_service(app)
            result = svc.import_completed_episodes(
                _dto(hash_, title, sonarr_id, title, episodes_payload)
            )

            assert result["action"] == "create_series_and_episodes"
            assert result["created_episode_count"] == 2

            t = TorrentsRepo().get_by_hash(hash_)
            assert t is not None

            s = SeriesRepo().get_by_sonarr_id(sonarr_id)
            assert s is not None
            assert s.title == title

            ep1 = EpisodesRepo().get_by_series_season_episode(s.id, 1, 1)
            ep2 = EpisodesRepo().get_by_series_season_episode(s.id, 1, 2)
            assert ep1 is not None and ep1.latest_torrent_id == t.id
            assert ep2 is not None and ep2.latest_torrent_id == t.id


# ---------------------------------------------------------------------------
# Test 2 — Series exists, episode exists, same hash → no-op
# ---------------------------------------------------------------------------

class TestSeriesExistsSameHash:
    def test_same_hash_no_changes(self, app, db_session):
        """
        Re-sending the same torrent for an existing episode must not modify
        any row and must return action="sync_completed_no_deletes".
        """
        with app.app_context():
            from app.repositories.episodes_repo import EpisodesRepo

            sonarr_id = _unique()
            hash_ = _unique()
            title = f"Same Hash Series {sonarr_id}"

            torrent = make_torrent(db_session, hash_=hash_, name=title)
            series = make_series(db_session, sonarr_id=sonarr_id, title=title)
            make_episode(db_session, series_id=series.id, season=1, episode=1,
                         title="Pilot", torrent_id=torrent.id)

            svc = _build_service(app)
            result = svc.import_completed_episodes(
                _dto(hash_, title, sonarr_id, title, [_ep(1, 1, "Pilot")])
            )

            assert result["action"] == "sync_completed_no_deletes"
            assert result["updated_episodes"] == []
            assert result["failed_episodes"] == []

            # Episode must still point to the same torrent
            ep = EpisodesRepo().get_by_series_season_episode(series.id, 1, 1)
            assert ep.latest_torrent_id == torrent.id


# ---------------------------------------------------------------------------
# Test 3 — Series exists, episode exists, new hash → update + delete old
# ---------------------------------------------------------------------------

class TestSeriesExistsDifferentHash:
    def test_new_hash_updates_episode_and_deletes_old_torrent(self, app, db_session):
        """
        A new torrent for an existing episode must:
        - update episode.latest_torrent_id to the new torrent
        - delete the old torrent row from the DB
        - return action="replace_and_cleanup"
        """
        with app.app_context():
            from app.repositories.episodes_repo import EpisodesRepo
            from app.repositories.torrents_repo import TorrentsRepo

            sonarr_id = _unique()
            old_hash = _unique()
            new_hash = _unique()
            title = f"Updated Series {sonarr_id}"

            old_torrent = make_torrent(db_session, hash_=old_hash, name=f"{title}.OLD")
            series = make_series(db_session, sonarr_id=sonarr_id, title=title)
            make_episode(db_session, series_id=series.id, season=1, episode=1,
                         title="Pilot", torrent_id=old_torrent.id)

            svc = _build_service(app)
            result = svc.import_completed_episodes(
                _dto(new_hash, f"{title}.NEW", sonarr_id, title, [_ep(1, 1, "Pilot")])
            )

            assert result["action"] == "replace_and_cleanup"

            # Episode now points to new torrent
            new_torrent = TorrentsRepo().get_by_hash(new_hash)
            assert new_torrent is not None
            ep = EpisodesRepo().get_by_series_season_episode(series.id, 1, 1)
            assert ep.latest_torrent_id == new_torrent.id

            # Old torrent deleted from DB
            assert TorrentsRepo().get_by_hash(old_hash) is None
            assert result["deleted_db_rows"] >= 1

    def test_new_hash_with_cross_seed_deletes_both(self, app, db_session):
        """
        When the old episode torrent has a cross-seed child, both must be
        deleted from the DB when the new torrent arrives.
        """
        with app.app_context():
            from app.repositories.torrents_repo import TorrentsRepo

            sonarr_id = _unique()
            old_hash = _unique()
            cross_hash = _unique()
            new_hash = _unique()
            title = f"CrossSeed Series {sonarr_id}"

            old_torrent = make_torrent(db_session, hash_=old_hash, name=f"{title}.PARENT")
            cross_torrent = make_torrent(db_session, hash_=cross_hash, name=f"{title}.CROSS")
            cross_torrent.cross_seed_id = old_torrent.id
            db_session.flush()

            series = make_series(db_session, sonarr_id=sonarr_id, title=title)
            make_episode(db_session, series_id=series.id, season=1, episode=1,
                         title="Pilot", torrent_id=old_torrent.id)

            svc = _build_service(app)
            result = svc.import_completed_episodes(
                _dto(new_hash, f"{title}.NEW", sonarr_id, title, [_ep(1, 1, "Pilot")])
            )

            assert result["action"] == "replace_and_cleanup"
            assert TorrentsRepo().get_by_hash(old_hash) is None
            assert TorrentsRepo().get_by_hash(cross_hash) is None
            assert result["deleted_db_rows"] >= 2


# ---------------------------------------------------------------------------
# Test 4 — Series exists, mix of new and existing episodes
# ---------------------------------------------------------------------------

class TestSeriesExistsMixedEpisodes:
    def test_new_episodes_created_existing_unchanged(self, app, db_session):
        """
        When the payload contains both existing episodes (same hash) and brand
        new episodes, only the new ones must be created; existing ones are
        left untouched.
        """
        with app.app_context():
            from app.repositories.episodes_repo import EpisodesRepo
            from app.repositories.torrents_repo import TorrentsRepo

            sonarr_id = _unique()
            existing_hash = _unique()
            new_hash = _unique()
            title = f"Mixed Series {sonarr_id}"

            existing_torrent = make_torrent(db_session, hash_=existing_hash, name=title)
            series = make_series(db_session, sonarr_id=sonarr_id, title=title)
            # S01E01 already exists with existing_torrent
            make_episode(db_session, series_id=series.id, season=1, episode=1,
                         title="Pilot", torrent_id=existing_torrent.id)

            svc = _build_service(app)
            # Send S01E01 (same hash) + S01E02 (new episode)
            result = svc.import_completed_episodes(
                _dto(existing_hash, title, sonarr_id, title,
                     [_ep(1, 1, "Pilot"), _ep(1, 2, "Second")])
            )

            # S01E01 was unchanged (same hash → "same"), S01E02 was created
            assert result["action"] == "sync_completed_no_deletes"
            assert "S01E02" in result["created_episodes"]
            assert result["updated_episodes"] == []

            ep2 = EpisodesRepo().get_by_series_season_episode(series.id, 1, 2)
            assert ep2 is not None
            new_torrent = TorrentsRepo().get_by_hash(existing_hash)
            assert ep2.latest_torrent_id == new_torrent.id

            # S01E01 untouched
            ep1 = EpisodesRepo().get_by_series_season_episode(series.id, 1, 1)
            assert ep1.latest_torrent_id == existing_torrent.id


# ---------------------------------------------------------------------------
# Test 5 — Multi-episode torrent upgrade (season pack)
# ---------------------------------------------------------------------------

class TestSeasonPackUpgrade:
    def test_all_episodes_updated_old_torrent_deleted(self, app, db_session):
        """
        Upgrading a full season pack: every episode in the payload has an
        existing DB row with the old torrent. After the call all episodes must
        point to the new torrent and the old torrent must be deleted.
        """
        with app.app_context():
            from app.repositories.episodes_repo import EpisodesRepo
            from app.repositories.torrents_repo import TorrentsRepo

            sonarr_id = _unique()
            old_hash = _unique()
            new_hash = _unique()
            title = f"Season Pack {sonarr_id}"

            old_torrent = make_torrent(db_session, hash_=old_hash, name=f"{title}.S01.OLD")
            series = make_series(db_session, sonarr_id=sonarr_id, title=title)
            for ep_num in range(1, 4):
                make_episode(db_session, series_id=series.id, season=1, episode=ep_num,
                             title=f"Episode {ep_num}", torrent_id=old_torrent.id)

            svc = _build_service(app)
            payload = [_ep(1, n) for n in range(1, 4)]
            result = svc.import_completed_episodes(
                _dto(new_hash, f"{title}.S01.NEW", sonarr_id, title, payload)
            )

            assert result["action"] == "replace_and_cleanup"
            assert len(result["deleted_episodes"]) == 3

            new_torrent = TorrentsRepo().get_by_hash(new_hash)
            assert new_torrent is not None
            for ep_num in range(1, 4):
                ep = EpisodesRepo().get_by_series_season_episode(series.id, 1, ep_num)
                assert ep.latest_torrent_id == new_torrent.id

            # Old torrent deleted (only one old torrent shared by all 3 episodes)
            assert TorrentsRepo().get_by_hash(old_hash) is None
            assert result["deleted_db_rows"] >= 1


# ---------------------------------------------------------------------------
# Test 6 — No sonarr_id → skipped, no orphan rows created
# ---------------------------------------------------------------------------

class TestNoSonarrId:
    def test_no_sonarr_id_returns_skipped_and_creates_no_rows(self, app, db_session):
        """
        When sonarr_id is None, import_completed_episodes must return
        action="skipped" and must NOT create any Torrent, Series, or Episode row.
        """
        with app.app_context():
            from app.repositories.torrents_repo import TorrentsRepo
            from app.repositories.series_repo import SeriesRepo

            hash_ = _unique()
            svc = _build_service(app)
            dto = {
                "torrent": {"hash": hash_, "sourcePath": "/data/unknown.mkv"},
                "sonarr_id": None,
                "title": "Unknown Series",
                "image": None,
                "episodes": [_ep(1, 1, "Pilot")],
            }
            result = svc.import_completed_episodes(dto)

            assert result["action"] == "skipped"
            assert result.get("reason") == "no_sonarr_id"
            # No DB rows must have been created
            assert TorrentsRepo().get_by_hash(hash_) is None
            assert SeriesRepo().get_by_sonarr_id(None) is None
