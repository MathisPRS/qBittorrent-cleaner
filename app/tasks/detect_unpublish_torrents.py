# app/tasks/detect_unpublish_torrents.py

from app import create_app
from app.logger import get_logger
from app.models.torrents import Torrents
from app.adapters.qbittorrent_adapter import QbittorrentAdapter


class QbTorrentAuditService:

    def __init__(self, app):
        self.app = app
        self.logger = get_logger(__name__, app=app)
        self.qb = QbittorrentAdapter()

        # catégories qu'on ignore
        self.ignored_categories = {"adultes", "autres"}

    # ------------------------------------------------
    # Public entrypoint
    # ------------------------------------------------

    def run(self):

        self.logger.info("===== START QB TORRENT AUDIT =====")

        db_torrents = Torrents.query.all()

        db_hashes = {
            (t.hash or "").strip().lower()
            for t in db_torrents
            if t.hash
        }

        self.logger.info("DB torrents count: %s", len(db_hashes))

        qb_torrents = self._get_qb_torrents()

        self.logger.info("qBittorrent torrents count: %s", len(qb_torrents))

        unknown_torrents = []

        for torrent in qb_torrents:

            torrent_hash = (torrent.get("hash") or "").strip().lower()

            if not torrent_hash:
                continue

            category = (torrent.get("category") or "").strip().lower()

            if category in self.ignored_categories:
                continue

            if torrent_hash not in db_hashes:
                unknown_torrents.append(torrent)

        if not unknown_torrents:
            self.logger.info("No unknown torrents found in qBittorrent")
        else:
            self.logger.warning(
                "Found %s torrent(s) present in qBittorrent but NOT in DB",
                len(unknown_torrents),
            )

            self._print_by_category(unknown_torrents)

        self.logger.info("===== END QB TORRENT AUDIT =====")

    # ------------------------------------------------

    def _get_qb_torrents(self):

        self.qb.login()

        try:
            torrents = self.qb.client.torrents_info()

            result = []

            for t in torrents:

                torrent_hash = getattr(t, "hash", None) or t.get("hash")
                name = getattr(t, "name", None) or t.get("name")
                category = getattr(t, "category", None) or t.get("category")
                tags = getattr(t, "tags", None) or t.get("tags")

                result.append({
                    "hash": (torrent_hash or "").lower(),
                    "name": name,
                    "category": category,
                    "tags": tags,
                })

            return result

        except Exception:
            self.logger.exception("Failed to fetch torrents from qBittorrent")
            return []

    # ------------------------------------------------

    def _print_by_category(self, torrents):

        films = []
        series = []
        animes = []
        cross_seed = []

        for torrent in torrents:

            category = (torrent.get("category") or "").lower()
            tags = (torrent.get("tags") or "").lower()

            if "cross-seed" in tags:
                cross_seed.append(torrent)
                continue

            if category == "films":
                films.append(torrent)
            elif category == "series":
                series.append(torrent)
            elif category == "animes":
                animes.append(torrent)

        self._print_group("FILMS", films)
        self._print_group("SERIES", series)
        self._print_group("ANIMES", animes)
        self._print_group("CROSS-SEED", cross_seed)

    # ------------------------------------------------

    def _print_group(self, title, torrents):

        if not torrents:
            return

        self.logger.warning("----- %s (%s) -----", title, len(torrents))

        for torrent in torrents:
            self.logger.warning(
                "hash=%s name=%s category=%s tags=%s",
                torrent.get("hash"),
                torrent.get("name"),
                torrent.get("category"),
                torrent.get("tags"),
            )


# ------------------------------------------------
# CLI entrypoint
# ------------------------------------------------

def main():

    print("START DETECT UNPUBLISH TORRENTS")

    app = create_app()

    with app.app_context():

        service = QbTorrentAuditService(app)
        service.run()


if __name__ == "__main__":
    main()