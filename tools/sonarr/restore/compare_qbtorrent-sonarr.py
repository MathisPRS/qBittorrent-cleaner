#!/usr/bin/env python3
"""
Sonarr per-episode catalog filtering against qBittorrent "series"/"films" category and cross-seed detection.

Outputs:
 - catalog_sonarr_filtered.json  : filtered & enriched sonarr (kept series with episodes that have at least one hash in qB)
 - catalog_sonarr_missing.json   : sonarr episodes that have NO hash in qB (kept minimal info)
 - qb_only_sonarr.json           : torrents in qB parents not present in sonarr catalog hashes, with cross_seed children

Edit the VAR_* variables below.
"""
from typing import Dict, Any, List, Set, Tuple
import requests
import json
import os
import sys
import re
from collections import defaultdict

# -------------------------
# CONFIG / VARIABLES (EDIT HERE)
# -------------------------
VAR_QBIT_HOST = "http://192.168.10.100:8080"   # include scheme and port if needed
VAR_QBIT_USER = "mreclus"
VAR_QBIT_PASS = "MatMai172356!!"

VAR_INPUT_CATALOG = "../../catalog.json"     # path to input catalog.json (expects sonarr section)
VAR_OUTPUT_FILTERED = "catalog_sonarr_filtered.json"
VAR_OUTPUT_MISSING = "catalog_sonarr_missing.json"
VAR_OUTPUT_QB_ONLY = "qb_only_sonarr.json"

# qBittorrent API endpoints (v2)
QB_LOGIN = "/api/v2/auth/login"
QB_TORRENTS_INFO = "/api/v2/torrents/info"

# Parent categories to consider as "episode parents" in qB (modify if needed)
PARENT_CATEGORIES = {"series", "films", "tv", "tv-shows", "séries"}

# -------------------------
# Helpers (shared ideas with radarr script)
# -------------------------
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
    s = str(h).strip().lower()
    m = re.search(r"[0-9a-f]{8,40}", s)
    if m:
        return m.group(0)
    return s

def extract_torrent_hash_from_qb_entry(t: Dict[str, Any]) -> str:
    for field in ("hash", "hashString", "hashes", "info_hash", "infoHash"):
        h = t.get(field)
        if h:
            # if list, pick first
            if isinstance(h, (list, tuple)) and h:
                return normalize_hash(h[0])
            return normalize_hash(h)
    raw = t.get("hashes")
    if isinstance(raw, (list, tuple)) and raw:
        return normalize_hash(raw[0])
    return ""

def is_cross_category(cat: str) -> bool:
    if not cat:
        return False
    return "cross" in cat.lower()

def detect_indexer_from_torrent(t: Dict[str, Any]) -> str:
    possible_fields = ["trackers", "tracker", "trackerHost", "rss_feed", "rssFeedUrl", "tags", "label", "webSeed", "creator"]
    for f in possible_fields:
        v = t.get(f)
        if not v:
            continue
        if isinstance(v, (list, tuple)):
            for el in v:
                if not el:
                    continue
                s = str(el).lower()
                if "ygg" in s:
                    return "ygg"
                if "lacale" in s or "la-cale" in s:
                    return "lacale"
                dm = re.search(r"(?:https?://)?([^/]+)", s)
                if dm:
                    return dm.group(1).split(":")[0]
            return ",".join([str(x) for x in v if x])
        else:
            s = str(v).lower()
            if "ygg" in s:
                return "ygg"
            if "lacale" in s or "la-cale" in s:
                return "lacale"
            m = re.search(r"(?:https?://)?([^/]+)", s)
            if m:
                return m.group(1).split(":")[0]
            return v
    name = (t.get("name") or "").lower()
    known = ["ygg", "lacale", "yggtorrent", "gktorrent", "tpb"]
    for k in known:
        if k in name:
            return k
    return ""

# -------------------------
# Sonarr-specific catalog parsing helpers
# -------------------------
def collect_sonarr_episode_hashes(sonarr_section: Any) -> Tuple[Dict[str, Dict[str, Any]], Set[str]]:
    """
    Try to extract a mapping:
      series_id -> { "title": series_title, "episodes": { episode_key -> episode_meta } }
    and a flat set of all episode hashes in the catalog.

    The function attempts to support multiple plausible shapes of Sonarr data.
    """
    series_map: Dict[str, Dict[str, Any]] = {}
    all_hashes: Set[str] = set()

    if not sonarr_section:
        return series_map, all_hashes

    # Case 1: sonarr_section is a dict of series
    if isinstance(sonarr_section, dict):
        # heuristics: each value is a series object if it contains "episodes" or "seasons"
        for series_id, sdata in sonarr_section.items():
            if not isinstance(sdata, dict):
                continue
            title = sdata.get("title") or sdata.get("seriesTitle") or sdata.get("name") or ""
            episodes_obj = sdata.get("episodes") or {}
            # episodes may be dict or list
            episodes_map = {}
            if isinstance(episodes_obj, dict):
                # episode_id -> meta
                for eid, emeta in episodes_obj.items():
                    meta_norm = _normalize_episode_meta(emeta)
                    if meta_norm:
                        episodes_map[str(eid)] = meta_norm
                        for h in meta_norm.get("all_hashes", []):
                            all_hashes.add(h)
            elif isinstance(episodes_obj, list):
                for em in episodes_obj:
                    epk = _episode_key_from_meta(em)
                    meta_norm = _normalize_episode_meta(em)
                    if meta_norm and epk:
                        episodes_map[epk] = meta_norm
                        for h in meta_norm.get("all_hashes", []):
                            all_hashes.add(h)
            # store series
            series_map[str(series_id)] = {"title": title, "episodes": episodes_map}
        return series_map, all_hashes

    # Case 2: sonarr_section is a list of episodes (flat)
    if isinstance(sonarr_section, list):
        # try to group by seriesId or seriesTitle
        grouped: Dict[str, Dict[str, Any]] = {}
        for em in sonarr_section:
            meta_norm = _normalize_episode_meta(em)
            if not meta_norm:
                continue
            series_id = str(em.get("seriesId") or em.get("tvdbId") or em.get("series") or "unknown_series")
            series_title = em.get("seriesTitle") or em.get("seriesName") or em.get("title") or "unknown"
            if series_id not in grouped:
                grouped[series_id] = {"title": series_title, "episodes": {}}
            epk = _episode_key_from_meta(em) or f"{meta_norm.get('season')}-{meta_norm.get('episode')}"
            grouped[series_id]["episodes"][epk] = meta_norm
            for h in meta_norm.get("all_hashes", []):
                all_hashes.add(h)
        return grouped, all_hashes

    # unknown shape -> return empty
    return series_map, all_hashes

def _episode_key_from_meta(em: Any) -> str:
    # prefer a stable id if present
    if not isinstance(em, dict):
        return ""
    eid = em.get("id") or em.get("episodeId") or em.get("episodeNumber") or em.get("uniqueId")
    if eid:
        return str(eid)
    # fallback to season-episode
    s = em.get("seasonNumber") or em.get("season") or em.get("seasonNumberRaw")
    e = em.get("episodeNumber") or em.get("episode") or em.get("episodeNumberRaw")
    if s is not None and e is not None:
        return f"S{int(s):02d}E{int(e):02d}"
    return ""

def _normalize_episode_meta(em: Any) -> Dict[str, Any]:
    """
    Normalize an episode entry from various possible shapes into:
      { "season": int, "episode": int, "title": str, "latest": <hash or ''>, "candidates": [...], "removed": [...], "all_hashes": [...] }
    """
    if not isinstance(em, dict):
        return {}
    season = em.get("seasonNumber") or em.get("season") or em.get("seasonNumberRaw") or em.get("seasonIndex") or em.get("season_nr")
    episode = em.get("episodeNumber") or em.get("episode") or em.get("episodeIndex") or em.get("ep")
    title = em.get("title") or em.get("episodeTitle") or em.get("name") or ""
    latest = em.get("latest") or em.get("downloaded") or em.get("hash") or em.get("currentHash") or ""
    candidates = em.get("candidates") or em.get("candidateHashes") or em.get("hashes") or []
    removed = em.get("removed") or em.get("deleted") or []
    # normalize
    latest_n = normalize_hash(latest) if latest else ""
    cand_norm = []
    if isinstance(candidates, (list, tuple)):
        cand_norm = [normalize_hash(c) for c in candidates if c]
    elif candidates:
        cand_norm = [normalize_hash(candidates)]
    removed_norm = []
    if isinstance(removed, (list, tuple)):
        removed_norm = [normalize_hash(r) for r in removed if r]
    elif removed:
        removed_norm = [normalize_hash(removed)]
    all_hashes = set()
    if latest_n:
        all_hashes.add(latest_n)
    for c in cand_norm:
        if c:
            all_hashes.add(c)
    for r in removed_norm:
        if r:
            all_hashes.add(r)
    return {
        "season": int(season) if season is not None else None,
        "episode": int(episode) if episode is not None else None,
        "title": title,
        "latest": latest_n,
        "candidates": cand_norm,
        "removed": removed_norm,
        "all_hashes": list(all_hashes)
    }

# -------------------------
# Main
# -------------------------
def main():
    # load catalog
    try:
        catalog = load_catalog(VAR_INPUT_CATALOG)
    except Exception as e:
        print("ERROR: cannot load catalog:", e, file=sys.stderr)
        sys.exit(2)

    sonarr_section = catalog.get("sonarr") or catalog.get("sonar") or catalog.get("sonarr_catalog") or {}
    if not sonarr_section:
        # attempt to use catalog root if it looks like sonarr episodes
        sonarr_section = catalog

    series_map, catalog_all_hashes = collect_sonarr_episode_hashes(sonarr_section)
    print(f"Sonarr: {len(series_map)} series, {len(catalog_all_hashes)} unique episode hashes in catalog.")

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

    # Separate torrents into parents (categories in PARENT_CATEGORIES) and children (category contains 'cross')
    parents = []
    children = []
    for t in torrents:
        cat = (t.get("category") or "").strip()
        if cat and cat.lower() in PARENT_CATEGORIES:
            parents.append(t)
        elif is_cross_category(cat):
            children.append(t)
    print(f"qB: {len(parents)} parent torrents (categories {PARENT_CATEGORIES}), {len(children)} children (cross*) found.")

    # Build maps for quick lookup
    qb_parent_hashes = set()
    qb_parent_hash_to_info: Dict[str, Dict[str, Any]] = {}
    parent_name_to_hashes: Dict[str, List[str]] = {}
    for t in parents:
        hn = extract_torrent_hash_from_qb_entry(t)
        if not hn:
            continue
        qb_parent_hashes.add(hn)
        indexer = detect_indexer_from_torrent(t)
        qb_parent_hash_to_info[hn] = {
            "name": t.get("name"),
            "category": t.get("category"),
            "indexer": indexer
        }
        name = (t.get("name") or "").strip()
        if name:
            parent_name_to_hashes.setdefault(name, []).append(hn)

    qb_child_hashes = set()
    qb_child_hash_to_info: Dict[str, Dict[str, Any]] = {}
    child_name_to_hashes: Dict[str, List[str]] = {}
    for t in children:
        hn = extract_torrent_hash_from_qb_entry(t)
        if not hn:
            continue
        qb_child_hashes.add(hn)
        indexer = detect_indexer_from_torrent(t)
        info = {"name": t.get("name"), "category": t.get("category"), "indexer": indexer}
        qb_child_hash_to_info[hn] = info
        name = (t.get("name") or "").strip()
        if name:
            child_name_to_hashes.setdefault(name, []).append(hn)

    # sets comparisons
    missing_hashes = sorted(list(catalog_all_hashes - qb_parent_hashes))
    qb_only_hashes = sorted(list(qb_parent_hashes - catalog_all_hashes))
    common_hashes = sorted(list(catalog_all_hashes & qb_parent_hashes))

    print(f" - Hashes in catalog but NOT in qB parents: {len(missing_hashes)}")
    print(f" - Hashes in qB parents but NOT in catalog: {len(qb_only_hashes)}")
    print(f" - Hashes present in both: {len(common_hashes)}")

    # Build outputs
    filtered_series: Dict[str, Any] = {}
    missing_series: Dict[str, Any] = {}

    # For each series, examine episodes
    for series_id, sdata in series_map.items():
        series_title = sdata.get("title", "")
        episodes = sdata.get("episodes", {}) or {}
        kept_eps = {}
        missing_eps_for_series = {}
        for ep_key, emeta in episodes.items():
            season = emeta.get("season")
            episode = emeta.get("episode")
            title = emeta.get("title")
            latest = emeta.get("latest") or ""
            candidates = [c for c in (emeta.get("candidates") or []) if c]
            # remove candidate equal to latest
            candidates = [c for c in candidates if c != latest]
            # keep only candidates present in qb parent hashes
            candidates_present = [c for c in candidates if c in qb_parent_hashes]
            has_latest_in_qb = (latest != "" and latest in qb_parent_hashes)
            has_any_candidate_in_qb = len(candidates_present) > 0

            if not has_latest_in_qb and not has_any_candidate_in_qb:
                # missing
                missing_eps_for_series[ep_key] = {
                    "season": season,
                    "episode": episode,
                    "title": title
                }
                continue

            # build kept episode entry
            entry: Dict[str, Any] = {
                "season": season,
                "episode": episode,
                "title": title
            }
            if has_latest_in_qb:
                entry["hash"] = latest
            elif candidates_present:
                entry["hash"] = candidates_present[0]
            else:
                entry["hash"] = ""

            # torrentTitle and indexer for chosen hash
            chosen_hash = entry.get("hash", "")
            torrent_title = None
            torrent_indexer = ""
            if chosen_hash and chosen_hash in qb_parent_hash_to_info:
                pinfo = qb_parent_hash_to_info[chosen_hash]
                torrent_title = pinfo.get("name")
                torrent_indexer = pinfo.get("indexer", "")
            entry["torrentTitle"] = torrent_title
            if torrent_indexer:
                entry["torrentIndexer"] = torrent_indexer

            # cross-seed detection: children with same name
            cross_seed_list = []
            if torrent_title:
                child_hashes = child_name_to_hashes.get(torrent_title, [])
                for ch in child_hashes:
                    cinfo = qb_child_hash_to_info.get(ch, {})
                    cross_seed_list.append({
                        "hash": ch,
                        "name": cinfo.get("name"),
                        "category": cinfo.get("category"),
                        "indexer": cinfo.get("indexer", "")
                    })
            entry["cross_seed"] = cross_seed_list

            kept_eps[ep_key] = entry

        if kept_eps:
            filtered_series[series_id] = {
                "title": series_title,
                "episodes": kept_eps
            }
        if missing_eps_for_series:
            missing_series[series_id] = {
                "title": series_title,
                "missing_episodes": missing_eps_for_series
            }

    # qb-only list (parents in qB not present in sonarr catalog hashes)
    qb_only_list = []
    for h in qb_only_hashes:
        info = qb_parent_hash_to_info.get(h, {})
        parent_name = info.get("name")
        cross_seed_list = []
        if parent_name:
            child_hashes = child_name_to_hashes.get(parent_name, [])
            for ch in child_hashes:
                cinfo = qb_child_hash_to_info.get(ch, {})
                cross_seed_list.append({
                    "hash": ch,
                    "name": cinfo.get("name"),
                    "category": cinfo.get("category"),
                    "indexer": cinfo.get("indexer", "")
                })
        qb_only_list.append({
            "hash": h,
            "name": parent_name,
            "category": info.get("category"),
            "indexer": info.get("indexer", ""),
            "cross_seed": cross_seed_list
        })

    # Prepare outputs
    catalog_filtered_out = {"sonarr": filtered_series}
    catalog_missing_out = {"sonarr": missing_series}
    qb_only_out = qb_only_list

    # Save files
    save_json(VAR_OUTPUT_FILTERED, catalog_filtered_out)
    save_json(VAR_OUTPUT_MISSING, catalog_missing_out)
    save_json(VAR_OUTPUT_QB_ONLY, qb_only_out)

    # Summary print
    print()
    print("=== Summary Sonarr ===")
    total_kept_eps = sum(len(s.get("episodes", {})) for s in filtered_series.values())
    total_missing_eps = sum(len(s.get("missing_episodes", {})) for s in missing_series.values())
    print(f"Series kept: {len(filtered_series)}, episodes kept: {total_kept_eps} -> {VAR_OUTPUT_FILTERED}")
    print(f"Series with missing episodes: {len(missing_series)}, total missing eps: {total_missing_eps} -> {VAR_OUTPUT_MISSING}")
    print(f"qB-only parent torrents (not present in Sonarr catalog): {len(qb_only_list)} -> {VAR_OUTPUT_QB_ONLY}")
    print()
    if qb_only_list:
        print("Examples of qb-only parents (first 8):")
        for e in qb_only_list[:8]:
            idx = e.get("indexer", "")
            print(f" - {e.get('name')} ({e.get('hash')}) indexer={idx} cross_children={len(e.get('cross_seed', []))}")
    if missing_series:
        print("Examples of series with missing episodes (first 8):")
        cnt = 0
        for sid, sd in missing_series.items():
            print(f" - series_id={sid} title={sd.get('title')} missing_eps={len(sd.get('missing_episodes', {}))}")
            cnt += 1
            if cnt >= 8:
                break
    print("Done.")

if __name__ == "__main__":
    main()
