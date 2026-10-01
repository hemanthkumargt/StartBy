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
    if not expected or provided != expected:
        raise ApiError("unauthorized", "Invalid cron secret", 401)

    notifier = get_notifier(current_app.config)
    counts = reminder_service.run_reminders(get_db(), notifier, now_iso=timeutil.utcnow_iso())
    return jsonify(counts), 200
