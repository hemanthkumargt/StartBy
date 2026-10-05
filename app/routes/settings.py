from flask import Blueprint, current_app, jsonify, request
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

    # The assistant's name is a voice-feature setting: with FEATURE_VOICE off it is
    # neither accepted nor reported, so the API equals v1.0's (I15).
    voice_on = current_app.config["FEATURE_VOICE"]
    extra = (
        {"assistant_name": body["assistant_name"]} if voice_on and "assistant_name" in body else {}
    )
    user = user_service.update_settings(
        get_db(),
        user_id=current_user.id,
        dark_mode=body.get("dark_mode"),
        timezone=body.get("timezone"),
        include_assistant_name=voice_on,
        **extra,
    )
    return jsonify(user), 200


@bp.patch("/me/profile")
@login_required
def update_profile():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ApiError("validation", "Request body must be JSON", 422)
    user = user_service.update_profile(
        get_db(),
        user_id=current_user.id,
        name=body.get("name"),
        email=body.get("email"),
    )
    return jsonify(user), 200
