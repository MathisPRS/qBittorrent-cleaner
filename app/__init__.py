import os
from urllib.parse import urlparse
from flask import Flask

from .config import configure_app
from .extensions import db, migrate, init_extensions  # <-- on ajoute init_extensions
from .api.routes import bp as api_bp


def create_app(config_filename: str | None = None):
    app = Flask(__name__, instance_relative_config=False)

    configure_app(app, config_filename)

    def _ensure_sqlite_dir(app):
        uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
        if uri.startswith("sqlite"):
            parsed = urlparse(uri)
            path = parsed.path
            if path and path != ":memory:":
                dirpath = os.path.dirname(path)
                if dirpath and not os.path.exists(dirpath):
                    os.makedirs(dirpath, exist_ok=True)

    _ensure_sqlite_dir(app)

    # Celery wiring (IMPORTANT)
    init_extensions(app)

    app.register_blueprint(api_bp, url_prefix="/api")

    @app.get("/")
    def root():
        return {"ok": True, "msg": "webhook-cleaner ready. POST /sonarr, /radarr."}

    return app