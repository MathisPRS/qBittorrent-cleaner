#!/usr/bin/env python3
from cleaner.logger import init_logging
from cleaner.config import SERVER_HOST, SERVER_PORT, DRY_RUN, ONLY_UPGRADES
from cleaner.routes import bp as cleaner_bp
from flask import Flask

log = init_logging()

def create_app():
    app = Flask(__name__)
    app.register_blueprint(cleaner_bp)

    @app.get("/")
    def root():
        return {"ok": True, "msg": "webhook-cleaner ready. Use POST /sonarr or /radarr."}

    return app

if __name__ == "__main__":
    app = create_app()
    log.info(f"Start webhook-cleaner on {SERVER_HOST}:{SERVER_PORT} (DRY_RUN={DRY_RUN}, ONLY_UPGRADES={ONLY_UPGRADES})")
    app.run(host=SERVER_HOST, port=SERVER_PORT)
