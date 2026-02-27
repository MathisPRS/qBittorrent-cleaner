# ==============================
# CONFIGURATION (à modifier ici)
# ==============================
QB_URL = "http://192.168.10.100:8080"
QB_USER = "mreclus"
QB_PASS = "MatMai172356!!"
HTTP_TIMEOUT = 10.0

# Catégories à exclure (insensible à la casse)
EXCLUDED_CATEGORIES = {"adultes", "autres"}
# ==============================

import sys
import json
import requests
from pathlib import Path

# --- rendre le projet importable ---
HERE = Path(__file__).resolve()
PROJECT_ROOT = HERE.parent.parent if HERE.parent.name == "app" else HERE.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# imports app
try:
    from app import create_app
    from app.extensions import db
    from app.models.torrents import Torrents
except Exception as e:
    err = {"error": "import_app_failed", "detail": str(e)}
    print(json.dumps(err, ensure_ascii=False), file=sys.stderr)
    sys.exit(2)


# ------------------------------
# Utils
# ------------------------------
def normalize_hash(h):
    if not h:
        return ""
    return str(h).strip().lower()


def fetch_qb_torrents():
    """
    Login to qBittorrent and fetch /api/v2/torrents/info
    Returns list of dicts (torrents).
    Raises RuntimeError on failure.
    """
    session = requests.Session()
    login_url = f"{QB_URL.rstrip('/')}/api/v2/auth/login"
    try:
        r = session.post(login_url, data={"username": QB_USER, "password": QB_PASS}, timeout=HTTP_TIMEOUT)
    except requests.RequestException as exc:
        raise RuntimeError(f"qB login network error: {exc}")

    # qBittorrent historically returns 200 and 'Ok.' on success.
    if r.status_code != 200:
        raise RuntimeError(f"qBittorrent login failed status={r.status_code} body={r.text}")

    info_url = f"{QB_URL.rstrip('/')}/api/v2/torrents/info"
    try:
        r = session.get(info_url, timeout=HTTP_TIMEOUT)
    except requests.RequestException as exc:
        raise RuntimeError(f"qB info network error: {exc}")

    if r.status_code != 200:
        raise RuntimeError(f"Failed to fetch torrents from qBittorrent status={r.status_code} body={r.text}")

    try:
        data = r.json()
    except ValueError:
        raise RuntimeError("qBittorrent returned non-JSON response for torrents/info")

    if not isinstance(data, list):
        raise RuntimeError("Unexpected qBittorrent response format (expected list)")

    return data


def get_db_hashes():
    """
    Returns a set of normalized hashes (strings) from the DB.
    """
    rows = db.session.query(Torrents.hash).all()
    return {normalize_hash(r[0]) for r in rows if r and r[0]}


# ------------------------------
# Main
# ------------------------------
def main():
    try:
        app = create_app()
    except Exception as e:
        print(json.dumps({"error": "create_app_failed", "detail": str(e)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(3)

    with app.app_context():
        try:
            db_hashes = get_db_hashes()
        except Exception as e:
            print(json.dumps({"error": "db_query_failed", "detail": str(e)}, ensure_ascii=False), file=sys.stderr)
            sys.exit(4)

    try:
        qb_torrents = fetch_qb_torrents()
    except RuntimeError as e:
        print(json.dumps({"error": "qb_fetch_failed", "detail": str(e)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(5)

    missing = []
    for t in qb_torrents:
        qb_hash = normalize_hash(t.get("hash"))
        if not qb_hash:
            # ignore items with no hash
            continue

        # if present in DB -> skip
        if qb_hash in db_hashes:
            continue

        # category filtering
        category = t.get("category") or t.get("label") or None
        if category:
            cat_norm = str(category).strip().lower()
            if cat_norm in EXCLUDED_CATEGORIES:
                # skip excluded categories
                continue

        missing.append({
            "name": t.get("name"),
            "hash": qb_hash,
            "size": t.get("size"),
            "added_on": t.get("added_on"),
            "category": category,
            # some useful id/fields to debug or later action
            "qb_id": t.get("hash") or t.get("hashString") or None
        })

    # unique JSON output to stdout
    print(json.dumps(missing, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
