"""
Shared pytest fixtures.

The app fixture creates a Flask application configured for testing against an
in-memory SQLite database.  All external adapters (qBittorrent, Sonarr, Radarr,
Gotify) are patched at import-time so no network calls are ever made.
"""
import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Patch heavy imports that hit the network or require Redis/Celery at import
# time, before `create_app` is ever called.
# ---------------------------------------------------------------------------
_QB_PATH = "app.adapters.qbittorrent_adapter.QbittorrentAdapter"
_GOTIFY_PATH = "app.adapters.gotify_adapter.notify_gotify"
_SONARR_PATH = "app.adapters.sonarr_adapter.SonarrAdapter"
_RADARR_PATH = "app.adapters.radarr_adapter.RadarrAdapter"
_SCHEDULER_PATH = "app.services.scheduler_services.SchedulerService"


@pytest.fixture(scope="session")
def app():
    """Create a Flask test application with an in-memory SQLite DB."""
    with (
        patch(_QB_PATH) as _qb,
        patch(_GOTIFY_PATH, return_value={}),
        patch(_SONARR_PATH),
        patch(_RADARR_PATH),
        patch(_SCHEDULER_PATH),
        # Prevent extensions.py from trying to connect to Redis at import
        patch("app.extensions.get_redis", return_value=MagicMock()),
    ):
        from app import create_app

        flask_app = create_app()
        flask_app.config.update(
            TESTING=True,
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            SQLALCHEMY_ECHO=False,
            # Disable Celery task sending during tests
            CELERY_TASK_ALWAYS_EAGER=True,
            CELERY_TASK_EAGER_PROPAGATES=True,
        )

        from app.extensions import db as _db

        with flask_app.app_context():
            _db.create_all()
            yield flask_app
            _db.drop_all()


@pytest.fixture()
def db_session(app):
    """
    Yield an active SQLAlchemy session, rolling back every change after the
    test so each test starts with a clean slate.
    """
    from app.extensions import db

    with app.app_context():
        connection = db.engine.connect()
        transaction = connection.begin()

        # Override the session to use our transactional connection
        db.session.configure(bind=connection)
        db.session.begin_nested()

        yield db.session

        db.session.rollback()
        db.session.remove()
        transaction.rollback()
        connection.close()


# ---------------------------------------------------------------------------
# Model factory helpers
# ---------------------------------------------------------------------------

def make_torrent(db_session, hash_="abc123", name="Test.Torrent.S01E01", indexer="ygg"):
    from app.models.torrents import Torrents

    t = Torrents(hash=hash_, name=name, indexer=indexer)
    db_session.add(t)
    db_session.flush()
    return t


def make_movie(db_session, radarr_id="r1", title="Test Movie", torrent_id=None):
    from app.models.movies import Movie

    m = Movie(radarr_id=radarr_id, title=title, latest_torrent_id=torrent_id)
    db_session.add(m)
    db_session.flush()
    return m


def make_series(db_session, sonarr_id="s1", title="Test Series"):
    from app.models.series import Series

    s = Series(sonarr_id=sonarr_id, title=title)
    db_session.add(s)
    db_session.flush()
    return s


def make_episode(db_session, series_id, season=1, episode=1, title="Ep", torrent_id=None):
    from app.models.episodes import Episodes

    e = Episodes(
        serie_id=series_id,
        season=season,
        episode=episode,
        title=title,
        latest_torrent_id=torrent_id,
    )
    db_session.add(e)
    db_session.flush()
    return e
