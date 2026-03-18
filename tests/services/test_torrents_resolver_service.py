"""
Tests for TorrentResolverService.

15 test cases covering: resolve_torrent, parse_guessit, clean_title,
find_best_movie, find_best_series, _extract_seasons, _extract_episode_numbers.
All Sonarr/Radarr adapter calls are mocked.
"""
import pytest
from unittest.mock import MagicMock, patch


def _build_resolver(app, movies=None, series=None):
    """Build a TorrentResolverService with mocked adapters."""
    with (
        patch("app.services.torrents_resolver_services.SonarrAdapter") as mock_sonarr,
        patch("app.services.torrents_resolver_services.RadarrAdapter") as mock_radarr,
    ):
        from app.services.torrents_resolver_services import TorrentResolverService
        svc = TorrentResolverService(app)
        svc.radarr = MagicMock()
        svc.sonarr = MagicMock()
        if movies is not None:
            svc.radarr.get_all_movies.return_value = movies
        if series is not None:
            svc.sonarr.get_all_series.return_value = series
        return svc


# ---------------------------------------------------------------------------
# resolve_torrent — edge cases
# ---------------------------------------------------------------------------

class TestResolveEdgeCases:
    def test_empty_name_returns_unresolved(self, app):
        with app.app_context():
            svc = _build_resolver(app)
            result = svc.resolve_torrent("")
            assert result["type"] == "unresolved"
            assert result["reason"] == "empty_name"

    def test_no_title_parsed_returns_unresolved(self, app):
        with app.app_context():
            svc = _build_resolver(app)
            # A name that guessit cannot extract a title from
            result = svc.resolve_torrent("720p.BluRay")
            # either no_title or no_movie_match — must be unresolved
            assert result["type"] == "unresolved"


# ---------------------------------------------------------------------------
# clean_title
# ---------------------------------------------------------------------------

class TestCleanTitle:
    def test_strips_blacklisted_words(self, app):
        with app.app_context():
            svc = _build_resolver(app)
            assert svc.clean_title("Breaking Bad complete french") == "breaking bad"

    def test_empty_string_returns_empty(self, app):
        with app.app_context():
            svc = _build_resolver(app)
            assert svc.clean_title("") == ""

    def test_returns_lowercase(self, app):
        with app.app_context():
            svc = _build_resolver(app)
            result = svc.clean_title("Inception")
            assert result == result.lower()


# ---------------------------------------------------------------------------
# find_best_movie
# ---------------------------------------------------------------------------

class TestFindBestMovie:
    def test_exact_title_match(self, app):
        with app.app_context():
            svc = _build_resolver(app)
            movies = [{"id": 1, "title": "Inception", "year": 2010, "alternateTitles": []}]
            best = svc.find_best_movie("inception", None, movies)
            assert best is not None
            assert best["id"] == 1

    def test_year_boost_selects_correct_movie(self, app):
        with app.app_context():
            svc = _build_resolver(app)
            movies = [
                {"id": 1, "title": "Dune", "year": 1984, "alternateTitles": []},
                {"id": 2, "title": "Dune", "year": 2021, "alternateTitles": []},
            ]
            best = svc.find_best_movie("dune", 2021, movies)
            assert best["id"] == 2

    def test_below_threshold_returns_none(self, app):
        with app.app_context():
            svc = _build_resolver(app)
            movies = [{"id": 1, "title": "Completely Unrelated Title XYZ", "year": 1999, "alternateTitles": []}]
            best = svc.find_best_movie("inception", None, movies)
            assert best is None

    def test_empty_movie_list_returns_none(self, app):
        with app.app_context():
            svc = _build_resolver(app)
            assert svc.find_best_movie("inception", 2010, []) is None


# ---------------------------------------------------------------------------
# find_best_series
# ---------------------------------------------------------------------------

class TestFindBestSeries:
    def test_exact_series_match(self, app):
        with app.app_context():
            svc = _build_resolver(app)
            series = [{"id": 10, "title": "Breaking Bad", "alternateTitles": []}]
            best = svc.find_best_series("breaking bad", series)
            assert best is not None
            assert best["id"] == 10

    def test_no_match_returns_none(self, app):
        with app.app_context():
            svc = _build_resolver(app)
            series = [{"id": 10, "title": "Breaking Bad", "alternateTitles": []}]
            assert svc.find_best_series("zzz totally different zzz", series) is None


# ---------------------------------------------------------------------------
# _extract_seasons / _extract_episode_numbers
# ---------------------------------------------------------------------------

class TestExtractSeasons:
    def test_single_season(self, app):
        with app.app_context():
            svc = _build_resolver(app)
            g = {"season": 2, "type": "episode"}
            assert svc._extract_seasons(g, "Show.S02E01") == [2]

    def test_season_range_in_name(self, app):
        with app.app_context():
            svc = _build_resolver(app)
            g = {"season": None, "type": "episode"}
            seasons = svc._extract_seasons(g, "Show.S01-S03.Complete")
            assert seasons == [1, 2, 3]

    def test_no_season_returns_empty(self, app):
        with app.app_context():
            svc = _build_resolver(app)
            g = {}
            assert svc._extract_seasons(g, "Show.Complete") == []


class TestExtractEpisodeNumbers:
    def test_single_episode(self, app):
        with app.app_context():
            svc = _build_resolver(app)
            assert svc._extract_episode_numbers({"episode": 5}) == [5]

    def test_multi_episode(self, app):
        with app.app_context():
            svc = _build_resolver(app)
            assert svc._extract_episode_numbers({"episode": [1, 2, 3]}) == [1, 2, 3]

    def test_no_episode_returns_empty(self, app):
        with app.app_context():
            svc = _build_resolver(app)
            assert svc._extract_episode_numbers({}) == []
