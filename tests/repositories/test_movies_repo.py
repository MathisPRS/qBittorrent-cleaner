"""
Tests for MoviesRepo.

7 test cases covering: create, get_by_radarr_id, get_by_title, update_latest_torrent_id.
"""
from tests.conftest import make_torrent, make_movie


class TestCreate:
    def test_create_movie(self, db_session):
        from app.repositories.movies_repo import MoviesRepo
        t = make_torrent(db_session, hash_="mv001")
        repo = MoviesRepo()
        m = repo.create(radarr_id="r100", title="Inception", latest_torrent_id=t.id)
        assert m is not None
        assert m.radarr_id == "r100"
        assert m.title == "Inception"
        assert m.latest_torrent_id == t.id

    def test_create_without_torrent(self, db_session):
        from app.repositories.movies_repo import MoviesRepo
        repo = MoviesRepo()
        m = repo.create(radarr_id="r200", title="Interstellar")
        assert m is not None
        assert m.latest_torrent_id is None


class TestGetByRadarrId:
    def test_found(self, db_session):
        from app.repositories.movies_repo import MoviesRepo
        make_movie(db_session, radarr_id="rfind1", title="Dune")
        repo = MoviesRepo()
        m = repo.get_by_radarr_id("rfind1")
        assert m is not None
        assert m.title == "Dune"

    def test_not_found(self, db_session):
        from app.repositories.movies_repo import MoviesRepo
        repo = MoviesRepo()
        assert repo.get_by_radarr_id("does_not_exist") is None

    def test_empty_id_returns_none(self, db_session):
        from app.repositories.movies_repo import MoviesRepo
        repo = MoviesRepo()
        assert repo.get_by_radarr_id("") is None


class TestUpdateLatestTorrentId:
    def test_updates_successfully(self, db_session):
        from app.repositories.movies_repo import MoviesRepo
        t1 = make_torrent(db_session, hash_="mvt1")
        t2 = make_torrent(db_session, hash_="mvt2")
        m = make_movie(db_session, radarr_id="ru1", torrent_id=t1.id)
        repo = MoviesRepo()
        updated = repo.update_latest_torrent_id("ru1", t2.id)
        assert updated is not None
        assert updated.latest_torrent_id == t2.id

    def test_unknown_radarr_id_returns_none(self, db_session):
        from app.repositories.movies_repo import MoviesRepo
        repo = MoviesRepo()
        assert repo.update_latest_torrent_id("ghost", 1) is None
