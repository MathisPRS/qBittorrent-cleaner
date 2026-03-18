"""
Tests for EpisodesRepo.

5 test cases covering: create, get_by_id (Bug Fix 2 regression),
get_by_series_season_episode, update_latest_torrent_id.
"""
from tests.conftest import make_torrent, make_series, make_episode


class TestCreate:
    def test_create_episode(self, db_session):
        from app.repositories.episodes_repo import EpisodesRepo
        s = make_series(db_session, sonarr_id="ep_sn1")
        t = make_torrent(db_session, hash_="ep_t1")
        repo = EpisodesRepo()
        ep = repo.create(serie_id=s.id, title="Pilot", season=1, episode=1, latest_torrent_id=t.id)
        assert ep is not None
        assert ep.season == 1
        assert ep.episode == 1
        assert ep.latest_torrent_id == t.id


class TestGetById:
    def test_get_by_id_uses_session_get(self, db_session):
        """Regression for Bug Fix 2: must use db.session.get(), not .query().get()."""
        from app.repositories.episodes_repo import EpisodesRepo
        s = make_series(db_session, sonarr_id="ep_sn2")
        ep = make_episode(db_session, series_id=s.id, season=2, episode=3)
        repo = EpisodesRepo()
        fetched = repo.get_by_id(ep.id)
        assert fetched is not None
        assert fetched.id == ep.id

    def test_get_by_id_missing_returns_none(self, db_session):
        from app.repositories.episodes_repo import EpisodesRepo
        repo = EpisodesRepo()
        assert repo.get_by_id(99999) is None


class TestGetBySeriesSeasonEpisode:
    def test_found(self, db_session):
        from app.repositories.episodes_repo import EpisodesRepo
        s = make_series(db_session, sonarr_id="ep_sn3")
        make_episode(db_session, series_id=s.id, season=1, episode=5)
        repo = EpisodesRepo()
        ep = repo.get_by_series_season_episode(s.id, 1, 5)
        assert ep is not None
        assert ep.episode == 5


class TestUpdateLatestTorrentId:
    def test_update(self, db_session):
        from app.repositories.episodes_repo import EpisodesRepo
        s = make_series(db_session, sonarr_id="ep_sn4")
        t1 = make_torrent(db_session, hash_="ep_t_old")
        t2 = make_torrent(db_session, hash_="ep_t_new")
        ep = make_episode(db_session, series_id=s.id, torrent_id=t1.id)
        repo = EpisodesRepo()
        updated = repo.update_latest_torrent_id(ep.id, t2.id)
        assert updated is not None
        assert updated.latest_torrent_id == t2.id
