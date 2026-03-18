"""
Tests for SeriesRepo.

4 test cases covering: create, get_by_sonarr_id.
"""
from tests.conftest import make_series


class TestCreate:
    def test_create_series(self, db_session):
        from app.repositories.series_repo import SeriesRepo
        repo = SeriesRepo()
        s = repo.create(sonarr_id="sn1", title="Breaking Bad")
        assert s is not None
        assert s.sonarr_id == "sn1"
        assert s.title == "Breaking Bad"

    def test_create_duplicate_returns_none(self, db_session):
        """On UNIQUE constraint violation create() rolls back and returns None."""
        from app.repositories.series_repo import SeriesRepo
        make_series(db_session, sonarr_id="sn2", title="Lost")
        repo = SeriesRepo()
        # duplicate sonarr_id → IntegrityError → rollback → None
        s = repo.create(sonarr_id="sn2", title="Lost duplicate")
        assert s is None


class TestGetBySonarrId:
    def test_found(self, db_session):
        from app.repositories.series_repo import SeriesRepo
        make_series(db_session, sonarr_id="snfind", title="The Wire")
        repo = SeriesRepo()
        s = repo.get_by_sonarr_id("snfind")
        assert s is not None
        assert s.title == "The Wire"

    def test_not_found_returns_none(self, db_session):
        from app.repositories.series_repo import SeriesRepo
        repo = SeriesRepo()
        assert repo.get_by_sonarr_id("ghost") is None
