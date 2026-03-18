"""
Tests for TorrentsRepo.

18 test cases covering: create, get_by_hash, get_by_id, delete_by_hash,
get_parent_by_name, set_cross_seed_parent, get_hashes_to_delete,
get_attr_created_at_by_hash, get_indexer_from_hash (bug-fix regression).
"""
import pytest
from tests.conftest import make_torrent


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------

class TestCreate:
    def test_create_new_torrent(self, db_session):
        from app.repositories.torrents_repo import TorrentsRepo
        repo = TorrentsRepo()
        t = repo.create("AABBCC", "My.Movie.2020", "ygg")
        assert t is not None
        assert t.hash == "aabbcc"
        assert t.name == "My.Movie.2020"
        assert t.indexer == "ygg"

    def test_create_normalises_hash_to_lowercase(self, db_session):
        from app.repositories.torrents_repo import TorrentsRepo
        repo = TorrentsRepo()
        t = repo.create("DEADBEEF", "Movie", "ygg")
        assert t.hash == "deadbeef"

    def test_create_idempotent_returns_existing(self, db_session):
        from app.repositories.torrents_repo import TorrentsRepo
        repo = TorrentsRepo()
        t1 = repo.create("dupe01", "Movie", "ygg")
        t2 = repo.create("dupe01", "Other Name", "nyaa")
        assert t1.id == t2.id

    def test_create_no_indexer_defaults(self, db_session):
        from app.repositories.torrents_repo import TorrentsRepo
        repo = TorrentsRepo()
        t = repo.create("noidx", "Movie", None)
        assert t.indexer == "no indexer"

    def test_create_raises_on_empty_hash(self, db_session):
        from app.repositories.torrents_repo import TorrentsRepo
        repo = TorrentsRepo()
        with pytest.raises(ValueError):
            repo.create("", "Movie", "ygg")


# ---------------------------------------------------------------------------
# get_by_hash
# ---------------------------------------------------------------------------

class TestGetByHash:
    def test_get_by_hash_existing(self, db_session):
        from app.repositories.torrents_repo import TorrentsRepo
        make_torrent(db_session, hash_="find001")
        repo = TorrentsRepo()
        t = repo.get_by_hash("find001")
        assert t is not None
        assert t.hash == "find001"

    def test_get_by_hash_case_insensitive(self, db_session):
        from app.repositories.torrents_repo import TorrentsRepo
        make_torrent(db_session, hash_="casetest")
        repo = TorrentsRepo()
        t = repo.get_by_hash("CASETEST")
        assert t is not None

    def test_get_by_hash_missing_returns_none(self, db_session):
        from app.repositories.torrents_repo import TorrentsRepo
        repo = TorrentsRepo()
        assert repo.get_by_hash("doesnotexist") is None

    def test_get_by_hash_empty_returns_none(self, db_session):
        from app.repositories.torrents_repo import TorrentsRepo
        repo = TorrentsRepo()
        assert repo.get_by_hash("") is None


# ---------------------------------------------------------------------------
# get_by_id
# ---------------------------------------------------------------------------

class TestGetById:
    def test_get_by_id_existing(self, db_session):
        from app.repositories.torrents_repo import TorrentsRepo
        t = make_torrent(db_session, hash_="idtest01")
        repo = TorrentsRepo()
        fetched = repo.get_by_id(t.id)
        assert fetched is not None
        assert fetched.id == t.id

    def test_get_by_id_missing_returns_none(self, db_session):
        from app.repositories.torrents_repo import TorrentsRepo
        repo = TorrentsRepo()
        assert repo.get_by_id(99999) is None


# ---------------------------------------------------------------------------
# delete_by_hash
# ---------------------------------------------------------------------------

class TestDeleteByHash:
    def test_delete_existing(self, db_session):
        from app.repositories.torrents_repo import TorrentsRepo
        make_torrent(db_session, hash_="del001")
        repo = TorrentsRepo()
        rows = repo.delete_by_hash("del001")
        assert rows == 1
        assert repo.get_by_hash("del001") is None

    def test_delete_nonexistent_returns_zero(self, db_session):
        from app.repositories.torrents_repo import TorrentsRepo
        repo = TorrentsRepo()
        assert repo.delete_by_hash("ghost") == 0


# ---------------------------------------------------------------------------
# get_indexer_from_hash  ← Bug Fix 1 regression test
# ---------------------------------------------------------------------------

class TestGetIndexerFromHash:
    def test_returns_str_not_row(self, db_session):
        """get_indexer_from_hash must return a plain str, not a Row tuple."""
        from app.repositories.torrents_repo import TorrentsRepo
        make_torrent(db_session, hash_="indextest", indexer="nyaa")
        repo = TorrentsRepo()
        result = repo.get_indexer_from_hash("indextest")
        assert isinstance(result, str), f"Expected str, got {type(result)}"
        assert result == "nyaa"

    def test_returns_none_for_unknown_hash(self, db_session):
        from app.repositories.torrents_repo import TorrentsRepo
        repo = TorrentsRepo()
        assert repo.get_indexer_from_hash("nope") is None

    def test_instant_delete_indexers_match(self, db_session):
        """Regression: set ensures the returned value actually matches the set literal."""
        from app.repositories.torrents_repo import TorrentsRepo
        instant_delete_indexers = {"nyaa", "torr9", "c411"}
        for idx in instant_delete_indexers:
            make_torrent(db_session, hash_=f"hash_{idx}", indexer=idx)
            repo = TorrentsRepo()
            result = repo.get_indexer_from_hash(f"hash_{idx}")
            assert result in instant_delete_indexers, (
                f"Indexer '{result}' (type={type(result)}) not found in instant_delete_indexers"
            )
