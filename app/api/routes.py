from flask import Blueprint, request, current_app
from ..controllers.radarr_controller import radarr_webhook
from ..controllers.sonarr_controller import sonarr_webhook
from ..controllers.torrents_controller import torrent_webhook, get_torrent_by_hash

bp = Blueprint("api", __name__)

# Film
@bp.post("/radarr")
def _radarr():
    return radarr_webhook(request, current_app)

# Serie / Anime
@bp.post("/sonarr")
def _sonarr():
    return sonarr_webhook(request, current_app)

# Torrent
@bp.post("/torrent")
def _torrent():
    return torrent_webhook(request, current_app)
@bp.get("/torrent")
def _get_torrent():
    return get_torrent_by_hash(request, current_app)