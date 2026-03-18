# app/services/torrents_resolver_services.py
from typing import Optional, List, Dict, Any
from guessit import guessit
from rapidfuzz import fuzz

from app.logger import get_logger
from app.adapters.sonarr_adapter import SonarrAdapter
from app.adapters.radarr_adapter import RadarrAdapter


# Return type contract for resolve_torrent()
# {
#   "type": "movie" | "episode" | "unresolved",
#   "torrent_name": str,
#   "title": str | None,
#   "year": int | None,
#   -- movie only --
#   "radarr_id": str | None,
#   "radarr_title": str | None,
#   -- episode/series only --
#   "sonarr_id": str | None,
#   "sonarr_title": str | None,
#   "season": int | None,          # None means all seasons
#   "episode_numbers": list[int],  # empty means whole season(s)
#   "episodes": list[dict],        # formatted Sonarr episode dicts
# }


class TorrentResolverService:

    def __init__(self, app):
        self.app = app
        self.logger = get_logger(__name__, app=app)

        self.sonarr = SonarrAdapter()
        self.radarr = RadarrAdapter()

    # ------------------------------------------------
    # PUBLIC ENTRYPOINT
    # ------------------------------------------------

    def resolve_torrent(self, torrent_name: str) -> Dict:
        """
        Main entry point: parse torrent_name with guessit, match against
        Sonarr/Radarr and return a structured resolution dict.
        Returns a dict with at minimum {"type": "unresolved"} on failure.
        """
        if not torrent_name:
            return {"type": "unresolved", "torrent_name": torrent_name, "reason": "empty_name"}

        g = self.parse_guessit(torrent_name)
        title = self.clean_title(g.get("title") or "")
        year = g.get("year")
        content_type = g.get("type")  # "movie" or "episode"

        # guessit sometimes tags "complete season" packs as movie
        name_lower = torrent_name.lower()
        if content_type == "movie" and any(
            x in name_lower for x in ["complete", "integrale", "intégrale", "s0", " s1", " s2", " s3", " s4", " s5"]
        ):
            content_type = "episode"

        if not title:
            self.logger.warning("[Resolver] No title detected for torrent_name=%s", torrent_name)
            return {"type": "unresolved", "torrent_name": torrent_name, "reason": "no_title"}

        self.logger.info("[Resolver] Parsed: type=%s title=%s year=%s season=%s episode=%s",
                         content_type, title, year, g.get("season"), g.get("episode"))

        if content_type == "movie":
            return self._resolve_movie(torrent_name, title, year, g)
        else:
            return self._resolve_episode(torrent_name, title, g)

    # ------------------------------------------------
    # PRIVATE: MOVIE
    # ------------------------------------------------

    def _resolve_movie(self, torrent_name: str, title: str, year: Optional[int], g: dict) -> Dict:
        movies = self.get_all_movies()
        best = self.find_best_movie(title=title, year=year, movies=movies)

        if not best:
            self.logger.warning("[Resolver] No movie match found for title=%s year=%s torrent=%s",
                                title, year, torrent_name)
            return {
                "type": "unresolved",
                "torrent_name": torrent_name,
                "title": title,
                "year": year,
                "reason": "no_movie_match",
            }

        self.logger.info("[Resolver] Movie match: radarr_id=%s title=%s year=%s",
                         best.get("id"), best.get("title"), best.get("year"))
        return {
            "type": "movie",
            "torrent_name": torrent_name,
            "title": title,
            "year": year,
            "radarr_id": str(best.get("id")),
            "radarr_title": best.get("title"),
            "radarr_data": best,
        }

    # ------------------------------------------------
    # PRIVATE: SERIES / EPISODES
    # ------------------------------------------------

    def _resolve_episode(self, torrent_name: str, title: str, g: dict) -> Dict:
        series_list = self.get_all_series()
        best = self.find_best_series(title=title, series_list=series_list)

        if not best:
            self.logger.warning("[Resolver] No series match found for title=%s torrent=%s", title, torrent_name)
            return {
                "type": "unresolved",
                "torrent_name": torrent_name,
                "title": title,
                "reason": "no_series_match",
            }

        sonarr_id = best.get("id")
        self.logger.info("[Resolver] Series match: sonarr_id=%s title=%s", sonarr_id, best.get("title"))

        # Resolve season range (e.g. S01-S04)
        seasons = self._extract_seasons(g, torrent_name)
        episode_numbers = self._extract_episode_numbers(g)

        # Fetch episodes from Sonarr for all targeted seasons
        all_episodes: List[dict] = []
        if sonarr_id is None:
            self.logger.error("[Resolver] sonarr_id is None, cannot fetch episodes")
        elif not seasons:
            # Complete series — fetch everything
            try:
                all_episodes = self.sonarr.get_all_episodes(int(sonarr_id))
            except Exception:
                self.logger.exception("[Resolver] Failed to fetch all episodes for sonarr_id=%s", sonarr_id)
        else:
            for season in seasons:
                try:
                    eps = self.sonarr.get_multiple_episodes(
                        series_id=int(sonarr_id),
                        season_number=season,
                        episode_numbers=episode_numbers if len(seasons) == 1 else None,
                    )
                    all_episodes.extend(eps)
                except Exception:
                    self.logger.exception("[Resolver] Failed to fetch episodes for sonarr_id=%s season=%s",
                                         sonarr_id, season)

        if not all_episodes:
            self.logger.warning("[Resolver] No episodes resolved for sonarr_id=%s seasons=%s torrent=%s",
                                sonarr_id, seasons, torrent_name)
            return {
                "type": "unresolved",
                "torrent_name": torrent_name,
                "title": title,
                "sonarr_id": str(sonarr_id),
                "sonarr_title": best.get("title"),
                "reason": "no_episodes_resolved",
            }

        self.logger.info("[Resolver] Resolved %d episode(s) for sonarr_id=%s seasons=%s",
                         len(all_episodes), sonarr_id, seasons)
        return {
            "type": "episode",
            "torrent_name": torrent_name,
            "title": title,
            "sonarr_id": str(sonarr_id),
            "sonarr_title": best.get("title"),
            "sonarr_data": best,
            "seasons": seasons,
            "episode_numbers": episode_numbers,
            "episodes": all_episodes,
        }

    # ------------------------------------------------
    # SEASON / EPISODE EXTRACTION HELPERS
    # ------------------------------------------------

    def _extract_seasons(self, g: dict, torrent_name: str) -> List[int]:
        """
        Returns a list of season numbers targeted by the torrent.
        Handles single season, season ranges (S01-S04), and whole-series packs.
        Returns [] to signal "all seasons / complete series".
        """
        season_raw = g.get("season")

        # guessit may return a list for ranges like S01-S04
        if isinstance(season_raw, list):
            try:
                return [int(s) for s in season_raw]
            except (TypeError, ValueError):
                pass

        if isinstance(season_raw, int):
            return [season_raw]

        # Try to detect S01-S04 pattern in the torrent name manually
        import re
        match = re.search(r"[Ss](\d{1,2})[-–][Ss]?(\d{1,2})", torrent_name)
        if match:
            start = int(match.group(1))
            end = int(match.group(2))
            if start <= end:
                return list(range(start, end + 1))

        # No season info → complete series
        return []

    def _extract_episode_numbers(self, g: dict) -> List[int]:
        """
        Returns a list of episode numbers from guessit output.
        Returns [] when targeting the whole season.
        """
        ep_raw = g.get("episode")
        if isinstance(ep_raw, list):
            try:
                return [int(e) for e in ep_raw]
            except (TypeError, ValueError):
                pass
        if isinstance(ep_raw, int):
            return [ep_raw]
        return []

    # ------------------------------------------------
    # PARSING
    # ------------------------------------------------

    def parse_guessit(self, torrent_name: str) -> dict:
        result = guessit(torrent_name)
        self.logger.debug("[Resolver] Guessit raw: %s", result)
        return result

    # ------------------------------------------------
    # UTILS
    # ------------------------------------------------

    def normalize(self, s: str) -> str:
        return (s or "").lower().replace(".", " ").strip()

    def score(self, a: str, b: str) -> float:
        return fuzz.ratio(self.normalize(a), self.normalize(b))

    def clean_title(self, title: str) -> str:
        if not title:
            return ""

        blacklist = [
            "complete",
            "integrale",
            "intégrale",
            "vostfr",
            "french",
            "multi",
        ]
        t = title.lower()

        for word in blacklist:
            t = t.replace(word, "")

        return t.strip()

    # ------------------------------------------------
    # MOVIES
    # ------------------------------------------------

    def get_all_movies(self) -> List[dict]:
        return self.radarr.get_all_movies()

    def find_best_movie(self, title: str, year: Optional[int], movies: List[dict]) -> Optional[dict]:
        best = None
        best_score = 0

        for m in movies:
            titles = [m.get("title", "")]

            for alt in m.get("alternateTitles", []):
                if isinstance(alt, dict):
                    titles.append(alt.get("title"))

            for candidate in titles:
                score = self.score(title, candidate)

                if year and m.get("year") == year:
                    score += 20

                if score > best_score:
                    best = m
                    best_score = score

        if best_score < 60:
            return None

        return best

    # ------------------------------------------------
    # SERIES
    # ------------------------------------------------

    def get_all_series(self) -> List[dict]:
        return self.sonarr.get_all_series()

    def find_best_series(self, title: str, series_list: List[dict]) -> Optional[dict]:
        best = None
        best_score = 0

        for s in series_list:
            titles = [s.get("title", "")]

            for alt in s.get("alternateTitles", []):
                if isinstance(alt, dict):
                    titles.append(alt.get("title"))

            for candidate in titles:
                score = self.score(title, candidate)

                if score > best_score:
                    best = s
                    best_score = score

        if best_score < 60:
            return None

        return best

    # ------------------------------------------------
    # EPISODES (legacy helper kept for compatibility)
    # ------------------------------------------------

    def get_episodes_for_torrent(
        self,
        series_id: int,
        season: Optional[int],
        episodes: Optional[Any],
        torrent_name: str,
    ) -> List[dict]:
        # épisode unique
        if isinstance(episodes, int) and season is not None:
            return self.sonarr.get_multiple_episodes(series_id, season, [episodes])

        # multi épisodes
        if isinstance(episodes, list) and season is not None:
            return self.sonarr.get_multiple_episodes(series_id, season, episodes)

        # saison complète
        if season is not None:
            return self.sonarr.get_multiple_episodes(series_id, season)

        # complete
        if "complete" in torrent_name.lower():
            return self.sonarr.get_all_episodes(series_id)

        return []
