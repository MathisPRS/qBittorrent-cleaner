# app/scripts/sync_torrents.py

import sys
from typing import List

from app import create_app
from app.extensions import db
from app.logger import get_logger

from app.models.torrents import Torrents
from app.models.movies import Movie
from app.models.episodes import Episodes

from app.repositories.torrents_repo import TorrentsRepo
from app.adapters.qbittorrent_adapter import QbittorrentAdapter
from app.services.commun_services import CommunService  # ✅ corrigé


class TorrentSyncService:

    def __init__(self, app, dry_run: bool = False):
        self.app = app
        self.logger = get_logger(__name__, app=app)

        self.torrents_repo = TorrentsRepo()
        self.qb = QbittorrentAdapter(dry_run=dry_run)
        self.commun_services = CommunService(app)  # ✅ avec S

        self.dry_run = dry_run

    # ==========================================================
    # ENTRYPOINT
    # ==========================================================

    def run(self):
        self.logger.info("===== START TORRENT SYNC =====")

        # ✅ LOGIN UNE SEULE FOIS
        try:
            self.qb.login()
        except Exception:
            self.logger.error("Unable to login to qBittorrent. Aborting sync.")
            return

        torrents = Torrents.query.all()
        self.logger.info("Found %s torrents in DB", len(torrents))

        for torrent in torrents:
            self._process_torrent(torrent)

        self.logger.info("===== END TORRENT SYNC =====")

    # ==========================================================
    # PROCESSING
    # ==========================================================

    def _process_torrent(self, torrent: Torrents):

        torrent_hash = (torrent.hash or "").strip().lower()
        if not torrent_hash:
            return

        self.logger.info(
            "Processing torrent id=%s hash=%s",
            torrent.id,
            torrent_hash
        )

        try:
            info_map = self.qb.info_map([torrent_hash])
        except Exception:
            self.logger.exception("Failed to retrieve info_map for hash=%s", torrent_hash)
            return

        if torrent_hash in info_map:
            self._handle_existing_torrent(torrent)
        else:
            self._handle_missing_torrent(torrent)

    # ==========================================================
    # EXISTING IN QBIT
    # ==========================================================

    def _handle_existing_torrent(self, torrent: Torrents):

        indexer = self.qb.get_indexer_from_hash(torrent.hash)

        if not indexer:
            return

        if torrent.indexer != indexer:
            self.logger.info(
                "Updating indexer for torrent id=%s (%s -> %s)",
                torrent.id,
                torrent.indexer,
                indexer
            )

            if not self.dry_run:
                try:
                    torrent.indexer = indexer
                    db.session.add(torrent)
                    db.session.commit()
                except Exception:
                    self.logger.exception(
                        "Failed to update indexer for torrent id=%s",
                        torrent.id
                    )
                    db.session.rollback()

    # ==========================================================
    # MISSING IN QBIT
    # ==========================================================

    def _handle_missing_torrent(self, torrent: Torrents):

        self.logger.warning(
            "Torrent missing in qBittorrent id=%s hash=%s",
            torrent.id,
            torrent.hash
        )

        # 🔎 Check Movie reference
        movie_ref = Movie.query.filter_by(
            latest_torrent_id=torrent.id
        ).first()

        # 🔎 Check Episode reference
        episode_ref = Episodes.query.filter_by(
            latest_torrent_id=torrent.id
        ).first()

        if movie_ref or episode_ref:

            if movie_ref:
                self.logger.warning(
                    "⚠ Would delete torrent id=%s but linked to Movie id=%s title=%s",
                    torrent.id,
                    movie_ref.id,
                    movie_ref.title
                )

            if episode_ref:
                self.logger.warning(
                    "⚠ Would delete torrent id=%s but linked to Episode id=%s S%02dE%02d",
                    torrent.id,
                    episode_ref.id,
                    episode_ref.season,
                    episode_ref.episode
                )

            return

        # Safe to delete
        self._delete_torrent_and_cross_seeds(torrent)

    # ==========================================================
    # DELETE
    # ==========================================================

    def _delete_torrent_and_cross_seeds(self, torrent: Torrents):

        hashes_to_delete: List[str] = self.torrents_repo.get_hashes_to_delete(
            parent_torrent_id=torrent.id
        )

        if not hashes_to_delete:
            return

        self.logger.info(
            "Deleting torrent id=%s and %s cross-seed(s)",
            torrent.id,
            len(hashes_to_delete) - 1
        )

        if self.dry_run:
            self.logger.info("[DRY_RUN] Would delete hashes: %s", hashes_to_delete)
            return

        try:
            self.commun_services.perform_deletion(hashes_to_delete)  # ✅ corrigé
        except Exception:
            self.logger.exception(
                "Deletion failed for torrent id=%s",
                torrent.id
            )


# ==========================================================
# CLI
# ==========================================================

def main():
    app = create_app()

    with app.app_context():
        dry_run = "--dry-run" in sys.argv
        service = TorrentSyncService(app, dry_run=dry_run)
        service.run()


if __name__ == "__main__":
    main()
