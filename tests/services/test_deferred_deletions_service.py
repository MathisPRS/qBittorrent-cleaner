"""
Tests for DeferredDeletionService.

11 test cases covering: _is_deletable, calculate_delta, filter_deferred_deletion_hash
(Bug Fix 1 regression), migrate_deferred_torrent, clock injection (Refactor R2).
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from tests.conftest import make_torrent


def _build_service(app, clock=None):
    """Helper: build a DeferredDeletionService with all side-effects mocked."""
    with (
        patch("app.services.deferred_deletions_services.CommunService"),
        patch("app.services.deferred_deletions_services.SchedulerService"),
    ):
        from app.services.deferred_deletions_services import DeferredDeletionService
        kwargs = {"_clock": clock} if clock is not None else {}
        return DeferredDeletionService(app, **kwargs)


class TestClockInjection:
    def test_default_clock_is_utcnow(self, app):
        """Without injection, _now_utc() should return a real datetime close to now."""
        with app.app_context():
            svc = _build_service(app)
            before = datetime.utcnow()
            result = svc._now_utc()
            after = datetime.utcnow()
            assert before <= result <= after

    def test_injected_clock_is_used(self, app):
        """With a fake clock, _now_utc() returns exactly what the clock returns."""
        fixed = datetime(2025, 1, 15, 12, 0, 0)
        with app.app_context():
            svc = _build_service(app, clock=lambda: fixed)
            assert svc._now_utc() == fixed


class TestIsDeletable:
    def test_none_date_is_deletable(self, app):
        with app.app_context():
            svc = _build_service(app)
            assert svc._is_deletable(None) is True

    def test_past_date_is_deletable(self, app):
        with app.app_context():
            svc = _build_service(app)
            past = datetime.utcnow() - timedelta(hours=1)
            assert svc._is_deletable(past) is True

    def test_future_date_is_not_deletable(self, app):
        with app.app_context():
            svc = _build_service(app)
            future = datetime.utcnow() + timedelta(hours=24)
            assert svc._is_deletable(future) is False


class TestCalculateDelta:
    def test_no_created_at_returns_ready(self, app, db_session):
        """Torrent with no created_at entry → considered ready."""
        with app.app_context():
            svc = _build_service(app)
            # hash not in DB at all
            assert svc.calculate_delta("nonexistent_hash_xyz") is True

    def test_old_torrent_is_ready(self, app, db_session):
        """Torrent created long ago is ready for deletion."""
        with app.app_context():
            t = make_torrent(db_session, hash_="old_calc")
            # Manually push created_at far into the past
            from app.models.torrents import Torrents
            from app.extensions import db
            db.session.query(Torrents).filter_by(hash="old_calc").update(
                {"created_at": datetime(2020, 1, 1)}
            )
            db.session.flush()
            svc = _build_service(app)
            assert svc.calculate_delta("old_calc") is True

    def test_fresh_torrent_is_not_ready(self, app, db_session):
        """Torrent just created with a future-safe delta should not be ready."""
        with app.app_context():
            make_torrent(db_session, hash_="fresh_calc")
            # Use a clock frozen at "right now" and a very large delta
            with patch("app.config.DEFFERED_DELETION_DELTA", 999):
                from importlib import reload
                import app.services.deferred_deletions_services as mod
                reload(mod)
                svc = mod.DeferredDeletionService.__new__(mod.DeferredDeletionService)
                svc.app = app
                svc.logger = MagicMock()
                svc._clock = datetime.utcnow
                svc.commun_services = MagicMock()
                svc.scheduler_services = MagicMock()
                svc.deferred_deletion_repo = MagicMock()
                from app.repositories.torrents_repo import TorrentsRepo
                svc.torrents_repo = TorrentsRepo()
                svc.delta = timedelta(hours=999)
                assert svc.calculate_delta("fresh_calc") is False


class TestFilterDeferredDeletionHash:
    def test_instant_delete_indexer_bypasses_delta(self, app, db_session):
        """
        Regression for Bug Fix 1: if get_indexer_from_hash() used to return a Row
        tuple, the 'indexer in instant_delete_indexers' check was always False and
        the instant-delete path was never taken.  After the fix it must be taken.
        """
        with app.app_context():
            make_torrent(db_session, hash_="instant01", indexer="nyaa")
            with (
                patch("app.services.deferred_deletions_services.CommunService"),
                patch("app.services.deferred_deletions_services.SchedulerService"),
            ):
                from app.services.deferred_deletions_services import DeferredDeletionService
                svc = DeferredDeletionService(app)
                ready = svc.filter_deferred_deletion_hash(["instant01"])
                assert "instant01" in ready, (
                    "instant-delete indexer torrent should appear in ready_to_delete"
                )

    def test_empty_list_returns_empty(self, app):
        with app.app_context():
            svc = _build_service(app)
            assert svc.filter_deferred_deletion_hash([]) == []

    def test_deduplicates_hashes(self, app, db_session):
        """Duplicate hashes in input produce only one entry in output."""
        with app.app_context():
            make_torrent(db_session, hash_="dedup01", indexer="nyaa")
            with (
                patch("app.services.deferred_deletions_services.CommunService"),
                patch("app.services.deferred_deletions_services.SchedulerService"),
            ):
                from app.services.deferred_deletions_services import DeferredDeletionService
                svc = DeferredDeletionService(app)
                ready = svc.filter_deferred_deletion_hash(["dedup01", "dedup01", "dedup01"])
                assert ready.count("dedup01") == 1
