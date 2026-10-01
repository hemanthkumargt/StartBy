from flask import Blueprint, current_app, jsonify

from app.db import get_db

bp = Blueprint("health", __name__)


@bp.get("/healthz")
def healthz():
    try:
        get_db().execute("SELECT 1").fetchone()
        db_ok = True
    except Exception as exc:  # noqa: BLE001 — health check must never crash
        current_app.logger.error("healthz_db_check_failed error=%s", exc)
        db_ok = False

    status = "ok" if db_ok else "degraded"
    return jsonify({"status": status, "db": db_ok}), 200 if db_ok else 503
