import hmac

from flask import Blueprint, current_app, jsonify, request

from app import timeutil
from app.db import get_db
from app.errors import ApiError
from app.feature_flags import read_feature_flags
from app.gcp import rest
from app.services import reminder_service
from app.services.notifier import get_notifier

bp = Blueprint("cron", __name__, url_prefix="/api/cron")
# Cloud Tasks callbacks live outside /api/cron but authenticate the same way.
internal_bp = Blueprint("internal", __name__, url_prefix="/api/internal")


def _require_cron_secret() -> None:
    expected = current_app.config["CRON_SECRET"]
    provided = request.headers.get("X-Cron-Secret", "")
    # Constant-time compare: a plain != leaks per-byte timing information
    # on this auth boundary.
    # Bytes, not str: compare_digest raises TypeError on a non-ASCII str, and
    # WSGI hands headers over as latin-1, so an odd header must be a 401, not a 500.
    if not expected or not hmac.compare_digest(provided.encode(), expected.encode()):
        raise ApiError("unauthorized", "Invalid cron secret", 401)


@bp.post("/reminders")
def send_reminders():
    _require_cron_secret()
    notifier = get_notifier(current_app.config)
    counts = reminder_service.run_reminders(
        get_db(),
        notifier,
        now_iso=timeutil.utcnow_iso(),
        flags=read_feature_flags(current_app.config),
    )
    current_app.extensions["integrations"].report_reminder_counts(counts)
    return jsonify(counts), 200


@bp.post("/backup")
def backup():
    """Cloud Scheduler -> consistent SQLite snapshot -> Cloud Storage."""
    _require_cron_secret()
    integrations = current_app.extensions["integrations"]
    if not integrations.storage_enabled:
        raise ApiError("not_configured", "GCS_BUCKET is not set", 503)
    try:
        name = integrations.backup_database(current_app.config["DATABASE_PATH"])
    except rest.GcpError as exc:
        current_app.logger.error("backup_upload_failed error=%s", exc)
        raise ApiError("upstream_error", "Backup upload failed", 502) from exc
    except ValueError as exc:  # database larger than the simple-upload limit
        current_app.logger.error("backup_too_large error=%s", exc)
        raise ApiError("too_large", "Database is too large for the simple backup", 507) from exc
    return jsonify({"object": name}), 200


@internal_bp.post("/start-now")
def start_now():
    """Cloud Tasks callback, fired at a task's start_by. 2xx tells Cloud
    Tasks the trigger is finished (sent, or nothing to send); 503 makes it
    retry with backoff — safe, because a send is only recorded on success."""
    _require_cron_secret()
    if not read_feature_flags(current_app.config)["estimates"]:
        # I15: start-now belongs to FEATURE_ESTIMATES. Triggers queued before
        # the flag was switched off must not keep emailing people.
        return jsonify({"sent": False, "reason": "not_eligible"}), 200
    body = request.get_json(silent=True)
    task_id = body.get("task_id") if isinstance(body, dict) else None
    if isinstance(task_id, bool) or not isinstance(task_id, int):
        raise ApiError("validation", "task_id must be an integer", 422)

    result = reminder_service.send_start_now_for_task(
        get_db(), get_notifier(current_app.config), task_id
    )
    if result["reason"] == "send_failed":
        raise ApiError("send_failed", "Email could not be sent; retry later", 503)
    if result["reason"] == "not_yet_red" and result.get("start_by"):
        # start_by drifted later (another task of the same tag finished and
        # changed the learned multiplier): follow it with a fresh trigger.
        current_app.extensions["integrations"].schedule_start_now(task_id, result["start_by"])
    return jsonify(result), 200
