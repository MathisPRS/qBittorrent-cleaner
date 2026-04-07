from typing import List, Dict, Optional, Any
import requests
from app.logger import get_logger
from app.config import SONARR_URL, SONARR_KEY


class SonarrAdapter:

    def __init__(self, base_url: str = SONARR_URL, api_key: str = SONARR_KEY):
        self.base = (base_url or "").rstrip("/")
        self.api_key = api_key
        self.logger = get_logger(__name__)

        self.session = requests.Session()
        self.session.headers.update({
            "X-Api-Key": self.api_key,
            "Content-Type": "application/json"
        })

    # ------------------------------------------------
    # INTERNAL
    # ------------------------------------------------

    def _get(self, path: str, params: dict = None) -> Any:
        url = f"{self.base}{path}"

        try:
            resp = self.session.get(url, params=params)
            resp.raise_for_status()
            return resp.json()

        except Exception:
            self.logger.exception("[Sonarr] GET failed: %s", url)
            return None

    def _format_episode(self, e: dict) -> dict:
        return {
            "id": e.get("id"),
            "episodeNumber": e.get("episodeNumber"),
            "seasonNumber": e.get("seasonNumber"),
            "title": e.get("title"),
            "overview": e.get("overview"),
            "airDate": e.get("airDate"),
            "airDateUtc": e.get("airDateUtc"),
            "seriesId": e.get("seriesId"),
            "tvdbId": e.get("tvdbId"),
        }

    # ------------------------------------------------
    # SERIES
    # ------------------------------------------------

    def get_all_series(self) -> List[dict]:
        data = self._get("/api/v3/series")
        return data or []

    def get_series(self, series_id: int) -> Optional[dict]:
        return self._get(f"/api/v3/series/{series_id}")

    def lookup_series(self, term: str) -> List[dict]:
        return self._get("/api/v3/series/lookup", params={"term": term}) or []

    # ------------------------------------------------
    # EPISODES
    # ------------------------------------------------

    def get_all_episodes(self, series_id: int) -> List[dict]:
        data = self._get("/api/v3/episode", params={"seriesId": series_id})

        if not data:
            return []

        return [self._format_episode(e) for e in data]

    def get_episode(
        self,
        series_id: int,
        season_number: int,
        episode_number: int,
    ) -> Optional[dict]:

        episodes = self.get_all_episodes(series_id)

        for e in episodes:
            if (
                e["seasonNumber"] == season_number
                and e["episodeNumber"] == episode_number
            ):
                return e

        return None

    def get_multiple_episodes(
        self,
        series_id: int,
        season_number: int,
        episode_numbers: Optional[List[int]] = None,
    ) -> List[dict]:

        episodes = self.get_all_episodes(series_id)

        result = []

        for e in episodes:

            if e["seasonNumber"] != season_number:
                continue

            # saison complète
            if not episode_numbers:
                result.append(e)
                continue

            if e["episodeNumber"] in episode_numbers:
                result.append(e)

        return result

    # ------------------------------------------------
    # QUEUE
    # ------------------------------------------------

    def get_queue(self, page_size: int = 500) -> list[dict]:
        """
        Returns all records currently in the Sonarr download queue (any status:
        downloading, importing, manualImport, delay, failed, etc.).

        Each record contains at minimum a 'downloadId' field (the torrent hash).
        """
        data = self._get(
            "/api/v3/queue",
            params={"pageSize": page_size, "includeUnknownSeriesItems": "true"},
        )
        if not data:
            return []
        return data.get("records", [])

    # ------------------------------------------------
    # CACHE
    # ------------------------------------------------

    def build_series_cache(self) -> Dict[str, dict]:
        """
        {
            "the boys": {...},
            "breaking bad": {...}
        }
        """
        series_list = self.get_all_series()
        cache = {}

        for s in series_list:
            title = (s.get("title") or "").lower().strip()
            if title:
                cache[title] = s

        self.logger.info("[Sonarr] cache built: %s series", len(cache))
        return cache