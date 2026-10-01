from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from app.db import get_db
from app.errors import ApiError
from app.services import user_service

bp = Blueprint("settings", __name__, url_prefix="/api")


@bp.patch("/me")
@login_required
def update_me():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ApiError("validation", "Request body must be JSON", 422)

    user = user_service.update_settings(
        get_db(),
        user_id=current_user.id,
        dark_mode=body.get("dark_mode"),
        timezone=body.get("timezone"),
    )
    return jsonify(user), 200
