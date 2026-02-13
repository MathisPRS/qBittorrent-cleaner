#!/usr/bin/env python3
"""
Filter catalog radarr against qBittorrent "films" category and detect cross-seed children
by matching torrents whose category contains "cross" to parents (category 'films') by exact name.

Outputs:
 - catalog_filtered.json  : filtered & enriched radarr (kept entries that have at least one hash in qB)
 - catalog_missing.json   : radarr entries that have NO hash in qB (only title & year kept)
 - qb_only.json           : torrents in qB (category 'films') not present in catalog hashes, with cross_seed children

Edit the VAR_* variables below.
"""
from typing import Dict, Any, List, Set
import requests
import json
import os
import sys

# -------------------------
# CONFIG / VARIABLES (EDIT HERE)
# -------------------------
VAR_QBIT_HOST = "http://192.168.10.100:8080"   # include scheme and port if needed
VAR_QBIT_USER = "mreclus"
VAR_QBIT_PASS = "MatMai172356!!"

VAR_INPUT_CATALOG = "./catalog.json"     # path to input catalog.json
VAR_OUTPUT_FILTERED = "catalog_filtered.json"
VAR_OUTPUT_MISSING = "catalog_missing.json"
VAR_OUTPUT_QB_ONLY = "qb_only.json"

# qBittorrent API endpoints (v2)
QB_LOGIN = "/api/v2/auth/login"
QB_TORRENTS_INFO = "/api/v2/torrents/info"

# --- helpers ---
def load_catalog(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Catalog file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path: str, obj: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)

def qb_login(session: requests.Session, host: str, user: str, password: str) -> None:
    url = host.rstrip("/") + QB_LOGIN
    data = {"username": user, "password": password}
    r = session.post(url, data=data, timeout=10)
    if r.status_code != 200:
        raise RuntimeError(f"qBittorrent login failed: HTTP {r.status_code} - {r.text}")
    return

def qb_get_torrents(session: requests.Session, host: str) -> List[Dict[str, Any]]:
    url = host.rstrip("/") + QB_TORRENTS_INFO
    r = session.get(url, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"qBittorrent torrents/info failed: HTTP {r.status_code} - {r.text}")
    return r.json()

def normalize_hash(h: Any) -> str:
    if h is None:
        return ""
    return str(h).strip().lower()

def build_catalog_hash_map(radarr_section: Dict[str, Any]) -> Dict[str, Set[str]]:
    # map movie_id -> set(hashes)
    m = {}
    for movie_id, meta in (radarr_section or {}).items():
        s = set()
        for c in meta.get("candidates", []) or []:
            if c:
                s.add(normalize_hash(c))
        latest = meta.get("latest")
        if latest:
            s.add(normalize_hash(latest))
        for r in meta.get("removed", []) or []:
            if r:
                s.add(normalize_hash(r))
        if s:
            m[str(movie_id)] = s
    return m

def is_cross_category(cat: str) -> bool:
    if not cat:
        return False
    return "cross" in cat.lower()

def main():
    # load catalog
    try:
        catalog = load_catalog(VAR_INPUT_CATALOG)
    except Exception as e:
        print("ERROR: cannot load catalog:", e, file=sys.stderr)
        sys.exit(2)

    radarr = catalog.get("radarr", {})
    if not isinstance(radarr, dict):
        print("ERROR: catalog has no 'radarr' dict", file=sys.stderr)
        sys.exit(2)

    # build catalog hash set
    movie_hashes_map = build_catalog_hash_map(radarr)
    catalog_all_hashes = set(h for s in movie_hashes_map.values() for h in s)

    print(f"Catalog: {len(movie_hashes_map)} radarr entries, {len(catalog_all_hashes)} unique hashes in catalog.")

    # qb login and get torrents
    session = requests.Session()
    try:
        qb_login(session, VAR_QBIT_HOST, VAR_QBIT_USER, VAR_QBIT_PASS)
    except Exception as e:
        print("ERROR: qB login failed:", e, file=sys.stderr)
        sys.exit(2)

    try:
        torrents = qb_get_torrents(session, VAR_QBIT_HOST)
    except Exception as e:
        print("ERROR: cannot fetch torrents:", e, file=sys.stderr)
        sys.exit(2)

    # Separate torrents into parents (category == films) and children (category contains 'cross')
    parents = []   # category films
    children = []  # category containing 'cross'
    for t in torrents:
        cat = (t.get("category") or "").strip()
        if cat.lower() == "films":
            parents.append(t)
        elif is_cross_category(cat):
            children.append(t)
    print(f"qB: {len(parents)} parents (films), {len(children)} children (cross*) found.")

    # Build maps for quick lookup
    qb_parent_hashes = set()
    qb_parent_hash_to_info: Dict[str, Dict[str, Any]] = {}
    parent_name_to_hashes: Dict[str, List[str]] = {}
    for t in parents:
        h = t.get("hash") or t.get("hashString") or t.get("hashes")
        if not h:
            continue
        hn = normalize_hash(h)
        qb_parent_hashes.add(hn)
        qb_parent_hash_to_info[hn] = {"name": t.get("name"), "category": t.get("category")}
        name = (t.get("name") or "").strip()
        if name:
            parent_name_to_hashes.setdefault(name, []).append(hn)

    qb_child_hashes = set()
    qb_child_hash_to_info: Dict[str, Dict[str, Any]] = {}
    child_name_to_hashes: Dict[str, List[str]] = {}
    for t in children:
        h = t.get("hash") or t.get("hashString") or t.get("hashes")
        if not h:
            continue
        hn = normalize_hash(h)
        qb_child_hashes.add(hn)
        info = {"name": t.get("name"), "category": t.get("category")}
        qb_child_hash_to_info[hn] = info
        name = (t.get("name") or "").strip()
        if name:
            child_name_to_hashes.setdefault(name, []).append(hn)

    # Overall qB hashes that are considered for "films" (parents)
    qb_films_hashes = qb_parent_hashes  # used for catalog comparisons (qb_only etc.)

    # sets comparisons (catalog vs qB parents)
    missing_hashes = sorted(list(catalog_all_hashes - qb_films_hashes))
    qb_only_hashes = sorted(list(qb_films_hashes - catalog_all_hashes))
    common_hashes = sorted(list(catalog_all_hashes & qb_films_hashes))
    print(f" - Hashes in catalog but NOT in qB (parents only): {len(missing_hashes)}")
    print(f" - Hashes in qB parents but NOT in catalog: {len(qb_only_hashes)}")
    print(f" - Hashes present in both: {len(common_hashes)}")

    # Build outputs
    filtered_radarr: Dict[str, Any] = {}
    missing_radarr: Dict[str, Any] = {}

    # Process each radarr entry
    for movie_id, meta in radarr.items():
        title = meta.get("title")
        year = meta.get("year")
        latest_raw = meta.get("latest")
        latest = normalize_hash(latest_raw) if latest_raw else ""
        # candidates list normalized
        candidates_raw = meta.get("candidates", []) or []
        candidates_norm = [normalize_hash(c) for c in candidates_raw if c]
        # 1) remove candidate equal to latest
        candidates_norm = [c for c in candidates_norm if c != latest]

        # 2) keep only candidates that exist on qB parents (only compare to parents, per request)
        candidates_present = [c for c in candidates_norm if c in qb_parent_hashes]

        # 3) decide if this movie has any hash in qb parents
        has_latest_in_qb = (latest != "" and latest in qb_parent_hashes)
        has_any_candidate_in_qb = len(candidates_present) > 0

        if not has_latest_in_qb and not has_any_candidate_in_qb:
            # NOTHING in qB for this movie -> missing (minimal info)
            missing_radarr[str(movie_id)] = {"title": title, "year": year}
            continue

        # kept entry -> build enriched object
        entry: Dict[str, Any] = {"title": title, "year": year}
        # include latest only if present in qB parents
        if has_latest_in_qb:
            entry["latest"] = latest
        # include candidates that are present in qB parents (may be empty list)
        entry["candidates"] = candidates_present

        # determine torrentTitle: prefer latest if present, else first candidate present
        chosen_hash = None
        if has_latest_in_qb:
            chosen_hash = latest
        elif candidates_present:
            chosen_hash = candidates_present[0]

        torrent_title = None
        if chosen_hash and chosen_hash in qb_parent_hash_to_info:
            torrent_title = qb_parent_hash_to_info[chosen_hash].get("name")

        entry["torrentTitle"] = torrent_title

        # NEW CROSS-SEED detection (children): compare torrentTitle to names of all child torrents
        cross_seed_list = []
        if torrent_title:
            # find children having exact same name
            child_hashes = child_name_to_hashes.get(torrent_title, [])
            for ch in child_hashes:
                info = qb_child_hash_to_info.get(ch, {})
                # store minimal child info: hash + name + category
                cross_seed_list.append({"hash": ch, "name": info.get("name"), "category": info.get("category")})
        entry["cross_seed"] = cross_seed_list

        # add entry
        filtered_radarr[str(movie_id)] = entry

    # qb-only list (parent torrents in qB 'films' not present in catalog hashes)
    qb_only_list = []
    for h in qb_only_hashes:
        info = qb_parent_hash_to_info.get(h, {})
        parent_name = info.get("name")

        # detect cross-seed children (same name)
        cross_seed_list = []
        if parent_name:
            child_hashes = child_name_to_hashes.get(parent_name, [])
            for ch in child_hashes:
                child_info = qb_child_hash_to_info.get(ch, {})
                cross_seed_list.append({
                    "hash": ch,
                    "name": child_info.get("name"),
                    "category": child_info.get("category")
                })

        qb_only_list.append({
            "hash": h,
            "name": parent_name,
            "category": info.get("category"),
            "cross_seed": cross_seed_list
        })

    # Prepare final JSONs
    catalog_filtered_out = {"radarr": filtered_radarr}
    catalog_missing_out = {"radarr": missing_radarr}
    qb_only_out = qb_only_list

    # Save files
    save_json(VAR_OUTPUT_FILTERED, catalog_filtered_out)
    save_json(VAR_OUTPUT_MISSING, catalog_missing_out)
    save_json(VAR_OUTPUT_QB_ONLY, qb_only_out)

    # Summary
    print()
    print("=== Summary ===")
    print(f"Filtered radarr entries (kept): {len(filtered_radarr)} -> {VAR_OUTPUT_FILTERED}")
    print(f"Missing radarr entries (no hash in qB parents): {len(missing_radarr)} -> {VAR_OUTPUT_MISSING}")
    print(f"qB-only parent torrents (in qB films but not in catalog): {len(qb_only_list)} -> {VAR_OUTPUT_QB_ONLY}")
    print()
    if qb_only_list:
        print("Examples of qb-only parents (first 8):")
        for e in qb_only_list[:8]:
            print(f" - {e.get('name')} ({e.get('hash')}) cross_children={len(e.get('cross_seed', []))}")
    if missing_radarr:
        print("Examples of missing radarr entries (first 8):")
        for k in list(missing_radarr.keys())[:8]:
            v = missing_radarr[k]
            print(f" - id={k} title={v.get('title')} year={v.get('year')}")
    print("Done.")

if __name__ == "__main__":
    main()
