import hmac

from flask import Blueprint, current_app, jsonify, request

from app import timeutil
from app.db import get_db
from app.errors import ApiError
from app.services import reminder_service
from app.services.notifier import get_notifier

bp = Blueprint("cron", __name__, url_prefix="/api/cron")


@bp.post("/reminders")
def send_reminders():
    expected = current_app.config["CRON_SECRET"]
    provided = request.headers.get("X-Cron-Secret", "")
    # Constant-time compare: a plain != leaks per-byte timing information
    # on this auth boundary.
    if not expected or not hmac.compare_digest(provided, expected):
        raise ApiError("unauthorized", "Invalid cron secret", 401)

    notifier = get_notifier(current_app.config)
    counts = reminder_service.run_reminders(get_db(), notifier, now_iso=timeutil.utcnow_iso())
    return jsonify(counts), 200
