# app/adapters/radarr_adapter.py

from typing import List, Dict, Optional, Any
import requests
from app.logger import get_logger
from app.config import RADARR_URL, RADARR_KEY


class RadarrAdapter:

    def __init__(self, base_url: str = RADARR_URL, api_key: str = RADARR_KEY):
        self.base = base_url.rstrip("/")
        self.api_key = api_key
        self.logger = get_logger(__name__)
        self.session = requests.Session()
        self.session.headers.update({"X-Api-Key": self.api_key})
        self.timeout = (5, 30)  # (connect, read) secondes

    # -----------------------------
    # INTERNAL
    # -----------------------------

    def _get(self, path: str, params: dict = None) -> Any:
        url = f"{self.base}{path}"
        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception:
            self.logger.exception("[Radarr] GET failed: %s", url)
            return None

    def _put(self, path: str, payload: dict) -> Any:
        url = f"{self.base}{path}"
        try:
            resp = self.session.put(url, json=payload, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json() if resp.text else True
        except Exception:
            self.logger.exception("[Radarr] PUT failed: %s", url)
            return None

    def _post(self, path: str, payload: dict) -> Any:
        url = f"{self.base}{path}"
        try:
            resp = self.session.post(url, json=payload, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json() if resp.text else True
        except Exception:
            self.logger.exception("[Radarr] POST failed: %s", url)
            return None

    # -----------------------------
    # TAGS (write)
    # -----------------------------

    def get_or_create_tag(self, label: str) -> Optional[int]:
        """Return the id of the Radarr tag `label`, creating it if needed."""
        label = (label or "").lower()
        for t in (self._get("/api/v3/tag") or []):
            if (t.get("label") or "").lower() == label:
                return t.get("id")
        created = self._post("/api/v3/tag", {"label": label})
        return created.get("id") if isinstance(created, dict) else None

    def update_movie(self, movie: dict) -> bool:
        """PUT a full movie resource back to Radarr (e.g. after mutating `tags`)."""
        mid = movie.get("id")
        return self._put(f"/api/v3/movie/{mid}", movie) is not None

    def set_movie_tags(self, radarr_id, add=None, remove=None) -> bool:
        """Add/remove tag *labels* on one movie (GET → mutate → PUT). Returns True if changed."""
        add = add or []
        remove = remove or []
        movie = self.get_movie(int(radarr_id))
        if not movie:
            return False
        tags = set(movie.get("tags") or [])
        add_ids = {self.get_or_create_tag(l) for l in add}
        add_ids = {i for i in add_ids if i is not None}
        label2id = {(t.get("label") or "").lower(): t.get("id")
                    for t in (self._get("/api/v3/tag") or [])}
        remove_ids = {label2id.get((l or "").lower()) for l in remove}
        remove_ids = {i for i in remove_ids if i is not None}
        new_tags = (tags | add_ids) - remove_ids
        if new_tags == tags:
            return False
        movie["tags"] = sorted(new_tags)
        return self.update_movie(movie)

    # -----------------------------
    # MOVIES
    # -----------------------------

    def get_all_movies(self) -> List[dict]:
        data = self._get("/api/v3/movie")
        return data or []

    def get_movie(self, movie_id: int) -> Optional[dict]:
        return self._get(f"/api/v3/movie/{movie_id}")

    def lookup_movie(self, term: str) -> List[dict]:
        return self._get("/api/v3/movie/lookup", params={"term": term}) or []

    # -----------------------------
    # QUEUE
    # -----------------------------

    def get_queue(self, page_size: int = 500) -> list[dict]:
        """
        Returns all records currently in the Radarr download queue (any status:
        downloading, importing, manualImport, delay, failed, etc.).

        Each record contains at minimum a 'downloadId' field (the torrent hash).
        """
        data = self._get(
            "/api/v3/queue",
            params={"pageSize": page_size, "includeUnknownMovieItems": "true"},
        )
        if not data:
            return []
        return data.get("records", [])

    # -----------------------------
    # UTILS
    # -----------------------------

    def build_movie_cache(self) -> Dict[str, dict]:
        """
        {
            "zion": {...},
            "inception": {...}
        }
        """
        movies = self.get_all_movies()
        cache = {}

        for m in movies:
            title = (m.get("title") or "").lower()
            year = m.get("year")

            if title:
                key = f"{title} {year}" if year else title
                cache[key] = m

        self.logger.info("[Radarr] cache built: %s movies", len(cache))
        return cache