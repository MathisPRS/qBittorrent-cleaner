import os
from urllib.parse import urlparse
from flask import Flask
from .config import configure_app  # on va créer cette helper pour charger config
from .extensions import db, migrate
from .api.routes import bp as api_bp

def create_app(config_filename: str | None = None):
    app = Flask(__name__, instance_relative_config=False)

    configure_app(app, config_filename)

    def _ensure_sqlite_dir(app):
        uri = app.config.get("SQLALCHEMY_DATABASE_URI", "") or ""
        if uri.startswith("sqlite"):
            # supporte sqlite:///absolute/path ou sqlite:////absolute/path
            # retire le préfixe pour récupérer le path
            # on parse pour éviter de casser si :memory:
            parsed = urlparse(uri)
            path = parsed.path  # pour sqlite, path contient le chemin
            if path and path != ":memory:":
                dirpath = os.path.dirname(path)
                if dirpath and not os.path.exists(dirpath):
                    os.makedirs(dirpath, exist_ok=True)
                    # optionnel: print/log
                    # print(f"created sqlite dir: {dirpath}")
   
    _ensure_sqlite_dir(app)
    db.init_app(app)
    migrate.init_app(app, db)

    app.register_blueprint(api_bp, url_prefix="/api")

    @app.get("/")
    def root():
        return {"ok": True, "msg": "webhook-cleaner ready. POST /sonarr, /radarr."}

    return app