"""
Integration tests for RadarrService.import_completed_movie.

All three scenarios are exercised against a real in-memory SQLite database.
Data is inserted before each test and rolled back at the end so every test
starts with a clean slate.

External I/O that must not run:
  - QbittorrentAdapter  → patched (qb.get_indexer_from_hash + qb.delete_torrents)
  - notify_gotify       → already patched session-wide in conftest.py

DeferredDeletionService receives a frozen clock set far in the past so every
candidate hash is immediately "ready to delete" (no deferral).
"""
import uuid
import pytest
from unittest.mock import MagicMock

from tests.conftest import make_torrent, make_movie


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unique() -> str:
    """Return a short unique string for hashes / ids."""
    return uuid.uuid4().hex[:12]


def _build_service(app):
    """
    Build a RadarrService whose external dependencies are controlled:
      - QbittorrentAdapter.get_indexer_from_hash  → returns "ygg"
      - QbittorrentAdapter.delete_torrents         → reports all hashes as deleted
      - DeferredDeletionService._clock             → frozen in the past (everything ready)
    """
    from app.services.radarr_services import RadarrService
    svc = RadarrService(app)

    # Make qB report every hash as deleted (no real network call)
    def _fake_delete(hashes, delete_files=True):
        return {
            "deleted": [(h, h) for h in hashes],
            "failed": [],
            "absent": [],
        }

    svc.qb.get_indexer_from_hash = MagicMock(return_value="ygg")
    svc.qb.delete_torrents = MagicMock(side_effect=_fake_delete)
    svc.commun_service.qb.get_indexer_from_hash = MagicMock(return_value="ygg")
    svc.commun_service.qb.delete_torrents = MagicMock(side_effect=_fake_delete)

    # Bypass deferred logic entirely: all candidate hashes are immediately ready.
    # This avoids dependency on qBittorrent indexer lookups and Celery scheduling
    # in the test environment.
    svc.deferred_deletion_services.filter_deferred_deletion_hash = lambda hashes: list(hashes)

    return svc


def _dto(hash_: str, name: str, radarr_id: str, title: str) -> dict:
    """Build a minimal import DTO as the Radarr controller would."""
    return {
        "torrent": {"hash": hash_, "sourcePath": f"/data/{name}"},
        "radarr_id": radarr_id,
        "title": title,
        "image": None,
    }


# ---------------------------------------------------------------------------
# Test 1 — Movie does not exist yet
# ---------------------------------------------------------------------------

class TestMovieNotInDB:
    def test_creates_movie_and_torrent(self, app, db_session):
        """
        Importing a completely unknown movie must:
        - create a Torrent row
        - create a Movie row linked to that torrent
        - return action="created"
        """
        with app.app_context():
            from app.repositories.movies_repo import MoviesRepo
            from app.repositories.torrents_repo import TorrentsRepo

            svc = _build_service(app)
            radarr_id = _unique()
            hash_ = _unique()
            title = f"New Movie {radarr_id}"

            result = svc.import_completed_movie(_dto(hash_, title, radarr_id, title))

            assert result["action"] == "created"

            # Torrent row exists in DB
            t = TorrentsRepo().get_by_hash(hash_)
            assert t is not None
            assert t.hash == hash_

            # Movie row exists and points to the torrent
            m = MoviesRepo().get_by_radarr_id(radarr_id)
            assert m is not None
            assert m.latest_torrent_id == t.id
            assert result["movie_id"] == m.id
            assert result["torrent_id"] == t.id


# ---------------------------------------------------------------------------
# Test 2 — Movie exists, same torrent hash → ignored
# ---------------------------------------------------------------------------

class TestMovieExistsSameTorrent:
    def test_same_hash_returns_ignored(self, app, db_session):
        """
        Sending the same torrent twice must not touch the DB and must return
        action="ignored".
        """
        with app.app_context():
            from app.repositories.movies_repo import MoviesRepo

            radarr_id = _unique()
            hash_ = _unique()
            title = f"Existing Movie {radarr_id}"

            # Seed: torrent + movie already in DB
            torrent = make_torrent(db_session, hash_=hash_, name=title)
            make_movie(db_session, radarr_id=radarr_id, title=title, torrent_id=torrent.id)

            svc = _build_service(app)
            result = svc.import_completed_movie(_dto(hash_, title, radarr_id, title))

            assert result["action"] == "ignored"
            assert result["movie_id"] == MoviesRepo().get_by_radarr_id(radarr_id).id

            # latest_torrent_id must be unchanged
            m = MoviesRepo().get_by_radarr_id(radarr_id)
            assert m.latest_torrent_id == torrent.id


# ---------------------------------------------------------------------------
# Test 3 — Movie exists, different torrent hash → update + old torrent deleted
# ---------------------------------------------------------------------------

class TestMovieExistsDifferentTorrent:
    def test_new_hash_updates_movie_and_deletes_old_torrent(self, app, db_session):
        """
        Sending a new torrent for an existing movie must:
        - create a Torrent row for the new hash
        - update movie.latest_torrent_id to the new torrent
        - delete the old torrent from the DB
        - return action="updated"
        """
        with app.app_context():
            from app.repositories.movies_repo import MoviesRepo
            from app.repositories.torrents_repo import TorrentsRepo

            radarr_id = _unique()
            old_hash = _unique()
            new_hash = _unique()
            title = f"Updated Movie {radarr_id}"

            # Seed: old torrent + movie
            old_torrent = make_torrent(db_session, hash_=old_hash, name=f"{title}.OLD")
            make_movie(db_session, radarr_id=radarr_id, title=title, torrent_id=old_torrent.id)

            svc = _build_service(app)
            result = svc.import_completed_movie(_dto(new_hash, f"{title}.NEW", radarr_id, title))

            assert result["action"] == "updated"

            # Movie now points to the new torrent
            m = MoviesRepo().get_by_radarr_id(radarr_id)
            new_torrent = TorrentsRepo().get_by_hash(new_hash)
            assert new_torrent is not None
            assert m.latest_torrent_id == new_torrent.id

            # Old torrent was deleted from DB
            assert TorrentsRepo().get_by_hash(old_hash) is None
            assert result["deleted_db_rows"] >= 1

    def test_new_hash_with_cross_seed_deletes_both(self, app, db_session):
        """
        When the old torrent has a cross-seed child, both the parent and the
        child must be deleted from the DB when the new torrent arrives.
        """
        with app.app_context():
            from app.repositories.movies_repo import MoviesRepo
            from app.repositories.torrents_repo import TorrentsRepo

            radarr_id = _unique()
            old_hash = _unique()
            cross_hash = _unique()
            new_hash = _unique()
            title = f"CrossSeed Movie {radarr_id}"

            # Seed: old parent torrent + cross-seed child + movie
            old_torrent = make_torrent(db_session, hash_=old_hash, name=f"{title}.PARENT")
            cross_torrent = make_torrent(db_session, hash_=cross_hash, name=f"{title}.CROSS")
            cross_torrent.cross_seed_id = old_torrent.id
            db_session.flush()
            make_movie(db_session, radarr_id=radarr_id, title=title, torrent_id=old_torrent.id)

            svc = _build_service(app)
            result = svc.import_completed_movie(_dto(new_hash, f"{title}.NEW", radarr_id, title))

            assert result["action"] == "updated"
            assert TorrentsRepo().get_by_hash(old_hash) is None
            assert TorrentsRepo().get_by_hash(cross_hash) is None
            assert result["deleted_db_rows"] >= 2


# ---------------------------------------------------------------------------
# Test 4 — No radarr_id → skipped, no orphan rows created
# ---------------------------------------------------------------------------

class TestNoRadarrId:
    def test_no_radarr_id_returns_skipped_and_creates_no_rows(self, app, db_session):
        """
        When radarr_id is None, import_completed_movie must return
        action="skipped" and must NOT create any Torrent or Movie row.
        """
        with app.app_context():
            from app.repositories.torrents_repo import TorrentsRepo
            from app.repositories.movies_repo import MoviesRepo

            hash_ = _unique()
            svc = _build_service(app)
            dto = {
                "torrent": {"hash": hash_, "sourcePath": "/data/unknown.mkv"},
                "radarr_id": None,
                "title": "Unknown Movie",
                "image": None,
            }
            result = svc.import_completed_movie(dto)

            assert result["action"] == "skipped"
            assert result.get("reason") == "no_radarr_id"
            # No DB rows must have been created
            assert TorrentsRepo().get_by_hash(hash_) is None
            assert MoviesRepo().get_by_radarr_id(None) is None
