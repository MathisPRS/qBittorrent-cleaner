from flask import Blueprint, request, jsonify, current_app
from ..controllers.radarr_controller import radarr_webhook

bp = Blueprint("api", __name__)

@bp.post("/radarr")
def _radarr():
    return radarr_webhook(request, current_app)



# @bp.post("/sonarr")
# def _sonarr():
#     return sonarr_webhook(request, current_app)
