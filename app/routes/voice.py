from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required

from app.db import get_db
from app.errors import ApiError
from app.feature_flags import read_feature_flags
from app.ratelimit import enforce
from app.services import (
    assistant_service,
    audio_service,
    briefing_service,
    capture_service,
    gemini_client,
)

bp = Blueprint("voice", __name__, url_prefix="/api/voice")


@bp.before_request
def _flag_gate() -> None:
    # Before @login_required: flag off => the route does not exist (I15).
    if not read_feature_flags(current_app.config)["voice"]:
        raise ApiError("not_found", "Not found", 404)


@bp.get("/briefing")
@login_required
def briefing():
    data = briefing_service.build_briefing(
        get_db(),
        user_id=current_user.id,
        user_name=current_user.name,
        tz_name=current_user.timezone,
        flags=read_feature_flags(current_app.config),
        assistant_name=current_user.assistant_name(current_app.config["ASSISTANT_NAME"]),
    )
    return jsonify(data), 200


@bp.post("/transcribe")
@login_required
def transcribe():
    """Speech -> text for browsers with no built-in speech recognition. The text is
    only placed in the capture box; nothing is created from it until the user
    reviews and confirms the drafted tasks (I14)."""
    capture_service.enforce_transcribe_limit(current_user.id)
    upload = request.files.get("audio")
    if upload is None:
        raise ApiError("validation", "No audio was sent", 422)
    mime = audio_service.normalize_mime(upload.mimetype)
    if mime is None:
        raise ApiError("validation", "That audio format isn't supported", 415)
    audio = upload.stream.read(audio_service.MAX_AUDIO_BYTES + 1)
    audio_service.validate_clip(audio)
    try:
        text = gemini_client.transcribe_audio(audio, mime, config=current_app.config)
    except gemini_client.GeminiUnavailable as exc:
        current_app.logger.warning("transcribe_unavailable reason=%s", exc)
        raise ApiError(
            "unavailable",
            "Voice transcription isn't available right now. Use Chrome, Edge or Safari for "
            "voice typing, or type your tasks.",
            503,
        ) from exc
    if not text:
        raise ApiError("validation", "I didn't catch any words — try again", 422)
    return jsonify({"text": text[: capture_service.CAPTURE_TEXT_MAX_CHARS]}), 200


@bp.post("/ask")
@login_required
def ask():
    """A spoken or typed question, answered from the user's own data. Read-only."""
    enforce(
        current_app.extensions["api_limiters"],
        "voice_ask",
        current_user.id,
        "Too many questions too quickly — wait a minute and retry",
    )
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ApiError("validation", "Request body must be JSON", 422)
    data = assistant_service.answer(
        get_db(),
        user_id=current_user.id,
        user_name=current_user.name,
        tz_name=current_user.timezone,
        flags=read_feature_flags(current_app.config),
        text=body.get("text"),
        assistant_name=current_user.assistant_name(current_app.config["ASSISTANT_NAME"]),
    )
    return jsonify(data), 200
