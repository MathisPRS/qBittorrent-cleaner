def norm_hash(h: str | None) -> str:
    return (h or "").lower().strip()

def ensure_episode(cat: dict, series_id: int, series_title: str | None,
                   episode_id: int, season: int | None,
                   epnum: int | None, ep_title: str | None) -> dict:
    s = cat["sonarr"].setdefault(str(series_id), {"seriesTitle": series_title, "episodes": {}, "packs": {}})
    e = s["episodes"].setdefault(str(episode_id), {
        "season": season, "episode": epnum, "title": ep_title,
        "latest": None, "candidates": [], "removed": [], "max_event_at": None
    })
    if season is not None and e.get("season") is None: e["season"] = season
    if epnum is not None and e.get("episode") is None: e["episode"] = epnum
    if ep_title and not e.get("title"): e["title"] = ep_title
    return e

def ensure_movie(cat: dict, movie_id: int, title: str | None, year: int | None) -> dict:
    m = cat["radarr"].setdefault(str(movie_id), {
        "title": title, "year": year, "latest": None, "candidates": [], "removed": [], "max_event_at": None
    })
    if title and not m.get("title"): m["title"] = title
    if year and not m.get("year"):   m["year"] = year
    return m
