from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required

from app.db import get_db
from app.errors import ApiError
from app.feature_flags import read_feature_flags
from app.services import voice_note_service

bp = Blueprint("voice_notes", __name__, url_prefix="/api/voice/notes")


@bp.before_request
def _flag_gate() -> None:
    # Before @login_required: flag off => the route does not exist (I15).
    if not read_feature_flags(current_app.config)["voice"]:
        raise ApiError("not_found", "Not found", 404)


@bp.get("")
@login_required
def list_notes():
    return jsonify({"notes": voice_note_service.list_notes(get_db(), user_id=current_user.id)}), 200


@bp.post("")
@login_required
def create_note():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ApiError("validation", "Request body must be JSON", 422)
    note = voice_note_service.create_note(
        get_db(), user_id=current_user.id, transcript=body.get("transcript")
    )
    return jsonify(note), 201


@bp.get("/<int:note_id>")
@login_required
def get_note(note_id: int):
    return jsonify(
        voice_note_service.get_note(get_db(), user_id=current_user.id, note_id=note_id)
    ), 200


@bp.delete("/<int:note_id>")
@login_required
def delete_note(note_id: int):
    voice_note_service.delete_note(get_db(), user_id=current_user.id, note_id=note_id)
    return "", 204
