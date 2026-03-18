"""
Tests for QbTorrentAuditService (detect_unpublish_torrents.py).

Covers: _classify, _filter_unknown, _record_stats, _process_film,
_ingest_series_resolution, _process_cross_seed, run() stats, dry_run mode,
unresolved collection and Gotify notification.
All I/O (qBittorrent, RadarrService, SonarrService, repos) is mocked.
"""
import pytest
from unittest.mock import MagicMock, patch
from tests.conftest import make_torrent


def _build_audit(app, dry_run=False, qb_torrents=None):
    """
    Build a QbTorrentAuditService with all external I/O mocked.
    Callers can further configure svc.radarr_service / svc.sonarr_service
    return values as needed.
    """
    from app.tasks.detect_unpublish_torrents import QbTorrentAuditService
    svc = QbTorrentAuditService.__new__(QbTorrentAuditService)
    svc.app = app
    svc.dry_run = dry_run
    svc.logger = MagicMock()

    # qBittorrent adapter
    svc.qb = MagicMock()
    svc.qb.login.return_value = None
    svc.qb.get_all_torrents.return_value = qb_torrents or []

    # Resolver
    svc.resolver = MagicMock()
    svc.resolver.resolve_torrent.return_value = {"type": "unresolved", "reason": "mocked"}

    # Real services — mocked at the service level
    svc.radarr_service = MagicMock()
    svc.radarr_service.import_completed_movie.return_value = {"action": "created"}

    svc.sonarr_service = MagicMock()
    svc.sonarr_service.import_completed_episodes.return_value = {"action": "create_series_and_episodes"}

    # commun_service + torrents_repo (used by cross-seed path)
    svc.commun_service = MagicMock()
    svc.torrents_repo = MagicMock()
    svc._unresolved = []

    return svc


# ---------------------------------------------------------------------------
# _classify
# ---------------------------------------------------------------------------

class TestClassify:
    def test_films_classified_correctly(self, app):
        with app.app_context():
            svc = _build_audit(app)
            films, series, cross, unclass = svc._classify([
                {"hash": "a", "category": "films", "tags": ""}
            ])
            assert len(films) == 1
            assert series == cross == unclass == []

    def test_series_classified_correctly(self, app):
        with app.app_context():
            svc = _build_audit(app)
            _, series, _, _ = svc._classify([
                {"hash": "b", "category": "series", "tags": ""}
            ])
            assert len(series) == 1

    def test_anime_classified_as_series(self, app):
        with app.app_context():
            svc = _build_audit(app)
            _, series, _, _ = svc._classify([
                {"hash": "c", "category": "animes", "tags": ""}
            ])
            assert len(series) == 1

    def test_cross_seed_tag_takes_priority_over_category(self, app):
        with app.app_context():
            svc = _build_audit(app)
            _, _, cross, _ = svc._classify([
                {"hash": "d", "category": "films", "tags": "cross-seed"}
            ])
            assert len(cross) == 1

    def test_unknown_category_unclassified(self, app):
        with app.app_context():
            svc = _build_audit(app)
            _, _, _, unclass = svc._classify([
                {"hash": "e", "category": "mystery", "tags": ""}
            ])
            assert len(unclass) == 1


# ---------------------------------------------------------------------------
# _filter_unknown
# ---------------------------------------------------------------------------

class TestFilterUnknown:
    def test_known_hash_filtered_out(self, app):
        with app.app_context():
            svc = _build_audit(app)
            qb = [{"hash": "known01", "name": "X", "category": "films", "tags": ""}]
            assert svc._filter_unknown(qb, {"known01"}) == []

    def test_unknown_hash_passes(self, app):
        with app.app_context():
            svc = _build_audit(app)
            qb = [{"hash": "new01", "name": "Y", "category": "films", "tags": ""}]
            assert len(svc._filter_unknown(qb, {"other"})) == 1

    def test_ignored_categories_skipped(self, app):
        with app.app_context():
            svc = _build_audit(app)
            qb = [{"hash": "adult01", "name": "Z", "category": "adultes", "tags": ""}]
            assert svc._filter_unknown(qb, set()) == []


# ---------------------------------------------------------------------------
# _record_stats
# ---------------------------------------------------------------------------

class TestRecordStats:
    def test_created_action_increments_ingested(self, app):
        with app.app_context():
            svc = _build_audit(app)
            stats = {"ingested": 0, "skipped": 0, "failed": 0}
            svc._record_stats({"action": "created"}, stats, "h", "n")
            assert stats == {"ingested": 1, "skipped": 0, "failed": 0}

    def test_error_action_increments_failed(self, app):
        with app.app_context():
            svc = _build_audit(app)
            stats = {"ingested": 0, "skipped": 0, "failed": 0}
            svc._record_stats({"action": "error", "message": "db_fail"}, stats, "h", "n")
            assert stats["failed"] == 1

    def test_ignored_action_increments_skipped(self, app):
        with app.app_context():
            svc = _build_audit(app)
            stats = {"ingested": 0, "skipped": 0, "failed": 0}
            svc._record_stats({"action": "ignored"}, stats, "h", "n")
            assert stats["skipped"] == 1

    def test_none_result_increments_failed(self, app):
        with app.app_context():
            svc = _build_audit(app)
            stats = {"ingested": 0, "skipped": 0, "failed": 0}
            svc._record_stats(None, stats, "h", "n")
            assert stats["failed"] == 1


# ---------------------------------------------------------------------------
# _process_film
# ---------------------------------------------------------------------------

class TestProcessFilm:
    def test_unresolved_increments_skipped(self, app):
        with app.app_context():
            svc = _build_audit(app)
            svc.resolver.resolve_torrent.return_value = {"type": "unresolved", "reason": "no_match"}
            stats = {"ingested": 0, "skipped": 0, "failed": 0}
            svc._process_film({"hash": "h1", "name": "Unknown 2020"}, stats)
            assert stats["skipped"] == 1
            svc.radarr_service.import_completed_movie.assert_not_called()

    def test_movie_resolution_calls_radarr_service(self, app):
        with app.app_context():
            svc = _build_audit(app)
            svc.resolver.resolve_torrent.return_value = {
                "type": "movie", "radarr_id": "42", "radarr_title": "Inception"
            }
            svc.radarr_service.import_completed_movie.return_value = {"action": "created"}
            stats = {"ingested": 0, "skipped": 0, "failed": 0}
            svc._process_film({"hash": "h2", "name": "Inception.2010"}, stats)
            svc.radarr_service.import_completed_movie.assert_called_once()
            call_dto = svc.radarr_service.import_completed_movie.call_args[0][0]
            assert call_dto["radarr_id"] == "42"
            assert call_dto["torrent"]["hash"] == "h2"
            assert stats["ingested"] == 1

    def test_dry_run_skips_radarr_service(self, app):
        with app.app_context():
            svc = _build_audit(app, dry_run=True)
            svc.resolver.resolve_torrent.return_value = {
                "type": "movie", "radarr_id": "1", "radarr_title": "Movie"
            }
            stats = {"ingested": 0, "skipped": 0, "failed": 0}
            svc._process_film({"hash": "h3", "name": "Movie 2020"}, stats)
            svc.radarr_service.import_completed_movie.assert_not_called()
            assert stats["skipped"] == 1


# ---------------------------------------------------------------------------
# _ingest_series_resolution
# ---------------------------------------------------------------------------

class TestIngestSeriesResolution:
    def test_episode_resolution_calls_sonarr_service(self, app):
        with app.app_context():
            svc = _build_audit(app)
            resolution = {
                "type": "episode", "sonarr_id": "7", "sonarr_title": "Lost",
                "episodes": [{"seasonNumber": 1, "episodeNumber": 1, "title": "Pilot"}],
            }
            svc.sonarr_service.import_completed_episodes.return_value = {
                "action": "create_series_and_episodes"
            }
            stats = {"ingested": 0, "skipped": 0, "failed": 0}
            svc._ingest_series_resolution("h4", "Lost.S01E01", resolution, stats)
            svc.sonarr_service.import_completed_episodes.assert_called_once()
            call_dto = svc.sonarr_service.import_completed_episodes.call_args[0][0]
            assert call_dto["sonarr_id"] == "7"
            assert call_dto["torrent"]["hash"] == "h4"
            assert len(call_dto["episodes"]) == 1
            assert stats["ingested"] == 1

    def test_wrong_type_increments_skipped(self, app):
        with app.app_context():
            svc = _build_audit(app)
            stats = {"ingested": 0, "skipped": 0, "failed": 0}
            svc._ingest_series_resolution(
                "h5", "name",
                {"type": "movie", "radarr_id": "1"},
                stats,
            )
            svc.sonarr_service.import_completed_episodes.assert_not_called()
            assert stats["skipped"] == 1


# ---------------------------------------------------------------------------
# _process_cross_seed
# ---------------------------------------------------------------------------

class TestProcessCrossSeed:
    def test_parent_not_found_increments_skipped(self, app):
        with app.app_context():
            svc = _build_audit(app)
            svc.torrents_repo.get_parent_by_name.return_value = None
            stats = {"ingested": 0, "skipped": 0, "failed": 0}
            svc._process_cross_seed({"hash": "cs1", "name": "Movie.2020"}, stats)
            assert stats["skipped"] == 1
            svc.commun_service.ensure_torrent_exists.assert_not_called()

    def test_successful_link_increments_ingested(self, app):
        with app.app_context():
            svc = _build_audit(app)
            parent = MagicMock()
            parent.id = 99
            svc.torrents_repo.get_parent_by_name.return_value = parent
            child = MagicMock()
            child.id = 10
            svc.commun_service.ensure_torrent_exists.return_value = child
            svc.torrents_repo.set_cross_seed_parent.return_value = True
            stats = {"ingested": 0, "skipped": 0, "failed": 0}
            svc._process_cross_seed({"hash": "cs2", "name": "Movie.2020"}, stats)
            svc.torrents_repo.set_cross_seed_parent.assert_called_once_with(
                child_hash="cs2", parent_id=99, child_name="Movie.2020"
            )
            assert stats["ingested"] == 1

    def test_dry_run_skips_everything(self, app):
        with app.app_context():
            svc = _build_audit(app, dry_run=True)
            stats = {"ingested": 0, "skipped": 0, "failed": 0}
            svc._process_cross_seed({"hash": "cs3", "name": "Movie.2020"}, stats)
            svc.torrents_repo.get_parent_by_name.assert_not_called()
            assert stats["skipped"] == 1


# ---------------------------------------------------------------------------
# run — integration
# ---------------------------------------------------------------------------

class TestRun:
    def test_no_unknown_returns_zero_stats(self, app, db_session):
        with app.app_context():
            make_torrent(db_session, hash_="run01")
            svc = _build_audit(app, qb_torrents=[
                {"hash": "run01", "name": "X", "category": "films", "tags": ""}
            ])
            result = svc.run()
            assert result["total_unknown"] == 0
            assert result["ingested"] == 0

    def test_dry_run_does_not_call_radarr_service(self, app, db_session):
        with app.app_context():
            svc = _build_audit(
                app,
                dry_run=True,
                qb_torrents=[{"hash": "dryrun01", "name": "Movie 2020", "category": "films", "tags": ""}],
            )
            svc.resolver.resolve_torrent.return_value = {
                "type": "movie", "radarr_id": "r1", "radarr_title": "Movie"
            }
            result = svc.run()
            svc.radarr_service.import_completed_movie.assert_not_called()
            assert result["skipped"] >= 1


# ---------------------------------------------------------------------------
# _process_film / _process_series — unresolved collection
# ---------------------------------------------------------------------------

class TestUnresolvedCollection:
    def test_process_film_unresolved_appends_to_list(self, app):
        with app.app_context():
            svc = _build_audit(app)
            svc.resolver.resolve_torrent.return_value = {
                "type": "unresolved", "reason": "no_movie_match"
            }
            stats = {"ingested": 0, "skipped": 0, "failed": 0}
            svc._process_film({"hash": "abc123", "name": "Unknown.Movie.2020"}, stats)

            assert stats["skipped"] == 1
            assert len(svc._unresolved) == 1
            assert svc._unresolved[0]["name"] == "Unknown.Movie.2020"
            assert svc._unresolved[0]["hash"] == "abc123"
            assert svc._unresolved[0]["reason"] == "no_movie_match"

    def test_process_series_unresolved_appends_to_list(self, app):
        with app.app_context():
            svc = _build_audit(app)
            svc.resolver.resolve_torrent.return_value = {
                "type": "unresolved", "reason": "no_series_match"
            }
            stats = {"ingested": 0, "skipped": 0, "failed": 0}
            svc._process_series({"hash": "def456", "name": "Unknown.Show.S01E01"}, stats)

            assert stats["skipped"] == 1
            assert len(svc._unresolved) == 1
            assert svc._unresolved[0]["name"] == "Unknown.Show.S01E01"
            assert svc._unresolved[0]["reason"] == "no_series_match"

    def test_resolved_torrent_does_not_append_to_unresolved(self, app):
        with app.app_context():
            svc = _build_audit(app)
            svc.resolver.resolve_torrent.return_value = {
                "type": "movie", "radarr_id": "42", "radarr_title": "Inception"
            }
            svc.radarr_service.import_completed_movie.return_value = {"action": "created"}
            stats = {"ingested": 0, "skipped": 0, "failed": 0}
            svc._process_film({"hash": "ghi789", "name": "Inception.2010"}, stats)

            assert svc._unresolved == []


# ---------------------------------------------------------------------------
# run() — Gotify notification for unresolved torrents
# ---------------------------------------------------------------------------

class TestRunGotifyNotification:
    def test_unresolved_torrents_trigger_gotify(self, app, db_session):
        """
        When run() encounters unresolved torrents, notify_gotify must be called
        once with the correct title and one line per unresolved torrent.
        """
        with app.app_context():
            svc = _build_audit(
                app,
                qb_torrents=[
                    {"hash": "unres01", "name": "No.Match.Movie.2020", "category": "films", "tags": ""},
                    {"hash": "unres02", "name": "No.Match.Show.S01E01", "category": "series", "tags": ""},
                ],
            )
            svc.resolver.resolve_torrent.return_value = {
                "type": "unresolved", "reason": "no_movie_match"
            }

            with patch("app.tasks.detect_unpublish_torrents.notify_gotify") as mock_notify:
                result = svc.run()

            mock_notify.assert_called_once()
            call_title, call_lines = mock_notify.call_args[0]
            assert call_title == "Webhook Cleaner : Audit — torrents non résolus"
            assert len(call_lines) == 2
            assert "No.Match.Movie.2020 — no_movie_match" in call_lines
            assert "No.Match.Show.S01E01 — no_movie_match" in call_lines
            assert result["skipped"] == 2

    def test_all_resolved_no_gotify(self, app, db_session):
        """
        When all torrents resolve successfully, notify_gotify must NOT be called.
        """
        with app.app_context():
            svc = _build_audit(
                app,
                qb_torrents=[
                    {"hash": "res01", "name": "Inception.2010", "category": "films", "tags": ""},
                ],
            )
            svc.resolver.resolve_torrent.return_value = {
                "type": "movie", "radarr_id": "42", "radarr_title": "Inception"
            }
            svc.radarr_service.import_completed_movie.return_value = {"action": "created"}

            with patch("app.tasks.detect_unpublish_torrents.notify_gotify") as mock_notify:
                svc.run()

            mock_notify.assert_not_called()
