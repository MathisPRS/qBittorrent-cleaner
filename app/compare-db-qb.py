#!/usr/bin/env python3

"""
Compare les torrents présents dans qBittorrent avec ceux en BDD.
Sortie: JSON uniquement -> torrents présents dans QB mais absents en BDD.
"""

# ==============================
# CONFIGURATION (à modifier ici)
# ==============================

QB_URL = "http://192.168.10.100:8080"
QB_USER = "mreclus"
QB_PASS = "MatMai172356!!"
HTTP_TIMEOUT = 10.0

# ==============================

import sys
import json
import requests
from pathlib import Path

# --- rendre le projet importable ---
HERE = Path(__file__).resolve()
PROJECT_ROOT = HERE.parent.parent if HERE.parent.name == "app" else HERE.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app import create_app
from app.extensions import db
from app.models.torrents import Torrents


# ------------------------------
# Utils
# ------------------------------

def normalize_hash(h):
    if not h:
        return ""
    return h.strip().lower()


def fetch_qb_torrents():
    session = requests.Session()

    # login
    login_url = f"{QB_URL}/api/v2/auth/login"
    r = session.post(
        login_url,
        data={"username": QB_USER, "password": QB_PASS},
        timeout=HTTP_TIMEOUT,
    )

    if r.status_code != 200:
        raise RuntimeError("qBittorrent login failed")

    # get torrents
    info_url = f"{QB_URL}/api/v2/torrents/info"
    r = session.get(info_url, timeout=HTTP_TIMEOUT)

    if r.status_code != 200:
        raise RuntimeError("Failed to fetch torrents from qBittorrent")

    return r.json()


def get_db_hashes():
    rows = db.session.query(Torrents.hash).all()
    return {normalize_hash(r[0]) for r in rows if r and r[0]}


# ------------------------------
# Main
# ------------------------------

def main():
    app = create_app()

    with app.app_context():
        db_hashes = get_db_hashes()

    qb_torrents = fetch_qb_torrents()

    missing = []

    for t in qb_torrents:
        qb_hash = normalize_hash(t.get("hash"))
        if not qb_hash:
            continue

        if qb_hash not in db_hashes:
            missing.append({
                "name": t.get("name"),
                "hash": qb_hash,
                "size": t.get("size"),
                "added_on": t.get("added_on"),
            })

    # SORTIE UNIQUE = JSON
    print(json.dumps(missing, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
