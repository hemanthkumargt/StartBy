from flask import Blueprint, current_app, jsonify
from flask_login import current_user, login_required

from app.db import get_db
from app.errors import ApiError
from app.feature_flags import read_feature_flags
from app.services import insights_service

bp = Blueprint("insights", __name__, url_prefix="/api")


@bp.get("/insights")
@login_required
def insights():
    flags = read_feature_flags(current_app.config)
    data = insights_service.get_insights(get_db(), user_id=current_user.id, flags=flags)
    return jsonify(data), 200


@bp.before_request
def _flag_gate() -> None:
    # Before @login_required: flag off means the route does not exist (I15).
    if not read_feature_flags(current_app.config)["insights"]:
        raise ApiError("not_found", "Not found", 404)
