#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sonarr_qb_clean_from_catalog.py

Utilise un catalogue Sonarr existant (format "clean" que tu as montré) et qBittorrent pour
produire un fichier sonarr_qb_clean.json listant, par série / épisode, les torrents présents aujourd'hui en qB.

Editer en tête:
 - VAR_INPUT_CATALOG : chemin vers ton JSON sonarr existant (structure attendue dans l'énoncé)
 - VAR_QBIT_HOST / VAR_QBIT_USER / VAR_QBIT_PASS
"""
from typing import Any, Dict, List, Set
import json
import re
from pathlib import Path
from datetime import datetime, timezone, timedelta
import requests

# ------------- CONFIG -------------
VAR_INPUT_CATALOG = "./catalog.json"   # <--- ton fichier clean (ex: le JSON que tu as montré)
VAR_QBIT_HOST = "http://192.168.10.100:8080"
VAR_QBIT_USER = "mreclus"
VAR_QBIT_PASS = "MatMai172356!!"
VAR_OUTPUT = Path("./sonarr_qb_clean.json")

# qB endpoints
QB_LOGIN = "/api/v2/auth/login"
QB_TORRENTS_INFO = "/api/v2/torrents/info"

# hash regex (préférer 40 mais accepte 32..64)
HASH_RE_40 = re.compile(r"[0-9a-fA-F]{40}")
HASH_RE_32_64 = re.compile(r"[0-9a-fA-F]{32,64}")

# timezone Europe/Paris (zoneinfo si dispo)
USE_ZONEINFO = False
try:
    from zoneinfo import ZoneInfo  # type: ignore
    PARIS_TZ = ZoneInfo("Europe/Paris")
    USE_ZONEINFO = True
except Exception:
    PARIS_TZ = timezone(timedelta(hours=1))

# ------------- helpers -------------
def load_catalog(path: str) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Input catalog not found: {path}")
    return json.loads(p.read_text(encoding="utf-8"))

def save_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")

def normalize_hash(s: Any) -> str:
    if not s:
        return ""
    txt = str(s).strip()
    m = HASH_RE_40.search(txt)
    if m:
        return m.group(0).lower()
    m2 = HASH_RE_32_64.search(txt)
    if m2:
        return m2.group(0).lower()
    return ""

def collect_hashes_from_episode(ep_obj: Dict[str, Any]) -> List[str]:
    """
    From episode object in catalog, collect latest + candidates + removed (if present),
    normalize and return unique list preserving order (latest first).
    """
    seen = []
    def add(h):
        nh = normalize_hash(h)
        if nh and nh not in seen:
            seen.append(nh)
    # latest
    latest = ep_obj.get("latest")
    if latest:
        add(latest)
    # candidates (list)
    for c in ep_obj.get("candidates", []) or []:
        add(c)
    # removed
    for r in ep_obj.get("removed", []) or []:
        add(r)
    return seen

def qb_login(session: requests.Session, host: str, user: str, password: str) -> None:
    url = host.rstrip("/") + QB_LOGIN
    r = session.post(url, data={"username": user, "password": password}, timeout=10)
    if r.status_code != 200:
        raise RuntimeError(f"qB login failed: {r.status_code} - {r.text}")

def qb_get_torrents(session: requests.Session, host: str) -> List[Dict[str, Any]]:
    url = host.rstrip("/") + QB_TORRENTS_INFO
    r = session.get(url, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"qB /torrents/info failed: {r.status_code} - {r.text}")
    return r.json() if isinstance(r.json(), list) else []

def extract_torrent_hash_from_qb_entry(t: Dict[str, Any]) -> str:
    for f in ("hash", "hashString", "hashes", "info_hash", "infoHash"):
        if f in t and t.get(f):
            v = t.get(f)
            if isinstance(v, (list, tuple)) and v:
                return normalize_hash(v[0])
            return normalize_hash(v)
    # try find in name
    if 'name' in t and t.get('name'):
        h = normalize_hash(t.get('name'))
        if h:
            return h
    try:
        return normalize_hash(json.dumps(t))
    except Exception:
        return ""

def detect_indexer_from_qb_entry(t: Dict[str, Any]) -> str:
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
                m = re.search(r"(?:https?://)?([^/:]+)", s)
                if m:
                    return m.group(1).split(":")[0]
            return ",".join([str(x) for x in v if x])
        else:
            s = str(v).lower()
            if "ygg" in s:
                return "ygg"
            if "lacale" in s or "la-cale" in s:
                return "lacale"
            m = re.search(r"(?:https?://)?([^/:]+)", s)
            if m:
                return m.group(1).split(":")[0]
            return v
    name = (t.get("name") or "").lower()
    for k in ("ygg", "lacale", "yggtorrent", "gktorrent", "tpb"):
        if k in name:
            return k
    return ""

def parse_date_to_paris(v) -> str:
    if v is None:
        return ""
    try:
        if isinstance(v, (int, float)):
            dt = datetime.fromtimestamp(int(v), tz=timezone.utc)
            return dt.astimezone(PARIS_TZ).isoformat() if USE_ZONEINFO else dt.astimezone(PARIS_TZ).isoformat()
    except Exception:
        pass
    try:
        s = str(v).strip()
        if s.endswith("Z"):
            s2 = s.replace("Z", "+00:00")
        else:
            s2 = s
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(PARIS_TZ).isoformat() if USE_ZONEINFO else dt.astimezone(PARIS_TZ).isoformat()
    except Exception:
        try:
            iv = int(float(str(v)))
            return parse_date_to_paris(iv)
        except Exception:
            return str(v)

def is_cross_category(cat: str) -> bool:
    if not cat:
        return False
    return "cross" in str(cat).lower()

# ------------- main -------------
def main():
    # load input catalog (the clean JSON you gave)
    try:
        catalog = load_catalog(VAR_INPUT_CATALOG)
    except Exception as e:
        print("ERROR loading input catalog:", e)
        return

    sonarr_section = catalog.get("sonarr") or catalog.get("sonar") or {}
    if not isinstance(sonarr_section, dict):
        print("Input catalog missing 'sonarr' dict.", flush=True)
        return

    # Build per-series structure from input catalog
    # Expectation: sonarr_section[seriesId]["seriesTitle"], ["episodes"][episodeId] -> episode obj
    series_map = {}  # seriesId -> {"seriesTitle":..., "episodes": {episodeId: ep_obj}}
    for s_id, s_meta in sonarr_section.items():
        try:
            sid = int(s_id)
        except Exception:
            sid = s_id
        stitle = s_meta.get("seriesTitle") or s_meta.get("title") or None
        episodes = s_meta.get("episodes") or {}
        series_map[sid] = {"seriesTitle": stitle, "episodes": episodes}

    # connect to qB
    s = requests.Session()
    try:
        qb_login(s, VAR_QBIT_HOST, VAR_QBIT_USER, VAR_QBIT_PASS)
    except Exception as e:
        print("ERROR qB login:", e)
        return

    try:
        torrents = qb_get_torrents(s, VAR_QBIT_HOST)
    except Exception as e:
        print("ERROR fetching qB torrents:", e)
        return

    # Build maps: hash -> info, name buckets parent/child
    qb_hash_info = {}
    parent_name_to_hashes = {}
    child_name_to_hashes = {}
    qb_child_info = {}
    for t in torrents:
        h = extract_torrent_hash_from_qb_entry(t)
        if not h:
            continue
        info = {"name": t.get("name"), "category": t.get("category"), "raw": t}
        # added raw
        for cand in ("added_on", "added_on_date", "creation_date", "added", "dateAdded", "added_date", "added_on_time"):
            if cand in t and t.get(cand) is not None:
                info["added_raw"] = t.get(cand)
                break
        if "added_raw" not in info and t.get("added_on") is not None:
            info["added_raw"] = t.get("added_on")
        info["indexer"] = detect_indexer_from_qb_entry(t)
        qb_hash_info[h] = info
        name = (t.get("name") or "").strip()
        cat = (t.get("category") or "").strip()
        if name:
            if is_cross_category(cat):
                child_name_to_hashes.setdefault(name, []).append(h)
                qb_child_info[h] = {"name": name, "indexer": info.get("indexer")}
            else:
                parent_name_to_hashes.setdefault(name, []).append(h)

    # Build output
    out = {"generated_at_paris": datetime.now(tz=PARIS_TZ).isoformat() if USE_ZONEINFO else datetime.now(tz=PARIS_TZ).isoformat(),
           "series": []}

    for sid, sdata in series_map.items():
        stitle = sdata.get("seriesTitle") or f"series_{sid}"
        episodes_obj = sdata.get("episodes") or {}
        episodes_out = []
        # iterate episodes in input order (or sorted by episode id)
        for ep_id in sorted(episodes_obj.keys(), key=lambda x: int(x) if str(x).isdigit() else x):
            ep = episodes_obj[ep_id] or {}
            season = ep.get("season")
            episode_no = ep.get("episode")
            ep_title = ep.get("title") or ep.get("episodeTitle") or None
            # collect hashes from this ep entry
            hashes = collect_hashes_from_episode(ep)
            torrents_list = []
            for hx in hashes:
                if not hx:
                    continue
                if hx in qb_hash_info:
                    qbinfo = qb_hash_info[hx]
                    # cross-seed detection by exact name match among child_name_to_hashes
                    cross = []
                    parent_name = qbinfo.get("name")
                    if parent_name:
                        child_hashes = child_name_to_hashes.get(parent_name, [])
                        for ch in child_hashes:
                            child_info = qb_child_info.get(ch, {})
                            cross.append({
                                "hash": ch,
                                "qb_name": child_info.get("name"),
                                "qb_indexer": child_info.get("indexer")
                            })
                    added_paris = parse_date_to_paris(qbinfo.get("added_raw")) if qbinfo.get("added_raw") is not None else ""
                    torrents_list.append({
                        "hash": hx,
                        "qb_name": qbinfo.get("name"),
                        "qb_indexer": qbinfo.get("indexer"),
                        "qb_added_on_paris": added_paris,
                        "cross_seed": cross
                    })
                else:
                    # omitted: hash not present in qB -> do not include
                    pass
            # Only include episode entry; episodes with zero torrents will have empty "torrents": []
            episodes_out.append({
                "episode_id": int(ep_id) if str(ep_id).isdigit() else ep_id,
                "season": season,
                "episode": episode_no,
                "title": ep_title,
                "torrents": torrents_list
            })

        out["series"].append({
            "series_id": sid,
            "seriesTitle": stitle,
            "episodes": episodes_out
        })

    # save
    save_json(VAR_OUTPUT, out)
    total_eps = sum(len(s["episodes"]) for s in out["series"])
    total_torrents = sum(len(ep["torrents"]) for s in out["series"] for ep in s["episodes"])
    print(f"Wrote {VAR_OUTPUT} with {len(out['series'])} series, {total_eps} episodes, {total_torrents} present torrents.")

if __name__ == "__main__":
    main()
