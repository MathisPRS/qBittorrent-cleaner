#!/usr/bin/env python3
from flask import Flask
from cleaner.logger import init_logging
from cleaner.api.routes import bp as api_bp
from cleaner.config import SERVER_HOST, SERVER_PORT

log = init_logging()

def create_app():
    app = Flask(__name__)
    app.register_blueprint(api_bp)
    return app

app = create_app()

@app.get("/")
def root():
    return {"ok": True, "msg": "webhook-cleaner ready. POST /sonarr, /radarr."}

if __name__ == "__main__":
    log.info(f"Start webhook-cleaner on {SERVER_HOST}:{SERVER_PORT}")
    app.run(host=SERVER_HOST, port=SERVER_PORT)
