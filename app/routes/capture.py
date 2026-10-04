from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required

from app.db import get_db
from app.errors import ApiError
from app.feature_flags import read_feature_flags
from app.services import capture_service

bp = Blueprint("capture", __name__, url_prefix="/api/capture")


@bp.before_request
def _flag_gate() -> None:
    # Runs before @login_required: with the flag off, even an anonymous
    # request must look exactly like the route never existed (I15), not 401.
    if not read_feature_flags(current_app.config)["smart_capture"]:
        raise ApiError("not_found", "Not found", 404)


def _json_body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("validation", "Request body must be JSON", 422)
    return data


@bp.post("/preview")
@login_required
def preview():
    flags = read_feature_flags(current_app.config)
    capture_service.enforce_rate_limit(current_user.id)
    pdf_bytes = None
    voice = False
    upload = request.files.get("file")
    if upload is not None:
        # +1 so an oversize upload is detected, not silently truncated.
        pdf_bytes = upload.stream.read(capture_service.CAPTURE_PDF_MAX_BYTES + 1)
        text = capture_service.extract_pdf_text(pdf_bytes)
    else:
        body = _json_body()
        text = body.get("text")
        voice = body.get("voice") is True
    result = capture_service.preview(
        user_id=current_user.id,
        text=text,
        tz_name=current_user.timezone,
        flags=flags,
        config=current_app.config,
        voice=voice,
    )
    if pdf_bytes is not None:
        # Only a PDF that was readable, within budget and produced a result is kept.
        current_app.extensions["integrations"].archive_pdf(current_user.id, pdf_bytes)
    return jsonify(result), 200


@bp.post("/confirm")
@login_required
def confirm():
    flags = read_feature_flags(current_app.config)
    created = capture_service.confirm(
        get_db(), user_id=current_user.id, tasks=_json_body().get("tasks"), flags=flags
    )
    return jsonify({"created": created}), 201
