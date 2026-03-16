# app/scripts/detect_unknown_qbittorrent_torrents.py

from flask import current_app
from app import create_app

from app.logger import get_logger
from app.models.torrents import Torrents

from app.adapters.qbittorrent_adapter import QbittorrentAdapter


class QbTorrentAuditService:

    def __init__(self, app):
        self.app = app
        self.logger = get_logger(__name__, app=app)

        self.qb = QbittorrentAdapter()

    # ------------------------------------------------
    # Public entrypoint
    # ------------------------------------------------

    def run(self):

        self.logger.info("===== START QB TORRENT AUDIT =====")

        # DB torrents
        db_torrents = Torrents.query.all()

        db_hashes = {
            (t.hash or "").strip().lower()
            for t in db_torrents
            if t.hash
        }

        self.logger.info("DB torrents count: %s", len(db_hashes))

        qb_hashes = self._get_qb_hashes()

        self.logger.info("qBittorrent torrents count: %s", len(qb_hashes))

        unknown_hashes = qb_hashes - db_hashes

        if not unknown_hashes:
            self.logger.info("No unknown torrents found in qBittorrent")
        else:
            self.logger.warning(
                "Found %s torrent(s) present in qBittorrent but NOT in DB",
                len(unknown_hashes),
            )

            self._print_unknown_torrents(unknown_hashes)

        self.logger.info("===== END QB TORRENT AUDIT =====")

    # ------------------------------------------------

    def _get_qb_hashes(self):

        self.qb.login()

        try:
            torrents = self.qb.client.torrents_info()

            hashes = set()

            for t in torrents:
                thash = getattr(t, "hash", None) or t.get("hash")
                if thash:
                    hashes.add(thash.lower())

            return hashes

        except Exception:
            self.logger.exception("Failed to fetch torrents from qBittorrent")
            return set()

    # ------------------------------------------------

    def _print_unknown_torrents(self, hashes):

        info_map = self.qb.info_map(list(hashes))

        for h in hashes:

            data = info_map.get(h)

            name = None
            if data:
                name = data.get("name")

            self.logger.warning(
                "Unknown torrent -> hash=%s name=%s",
                h,
                name,
            )


# ------------------------------------------------
# CLI entrypoint
# ------------------------------------------------

def main():

    app = create_app()

    with app.app_context():

        service = QbTorrentAuditService(app)
        service.run()


if __name__ == "__main__":
    main()