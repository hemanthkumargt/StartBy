import hmac
import secrets

from flask import Blueprint, current_app, jsonify, redirect, request, session
from flask_login import current_user, login_required

from app.db import get_db
from app.errors import ApiError
from app.feature_flags import read_feature_flags
from app.gcp import dispatcher
from app.repositories import calendar_repo
from app.services import calendar_service, task_service

bp = Blueprint("calendar", __name__)

_STATE_KEY = "calendar_oauth_state"


def _require_configured() -> None:
    if not calendar_service.is_configured(current_app.config):
        raise ApiError("not_found", "Not found", 404)


@bp.get("/calendar/connect")
@login_required
def connect():
    _require_configured()
    state = secrets.token_urlsafe(32)
    session[_STATE_KEY] = state
    return redirect(calendar_service.authorization_url(current_app.config, state))


@bp.get("/calendar/callback")
@login_required
def callback():
    _require_configured()
    expected = session.pop(_STATE_KEY, "")
    provided = request.args.get("state", "")
    # State ties this callback to a connect that THIS browser session began:
    # without it, a crafted link could attach an attacker's calendar.
    # Compare bytes: compare_digest raises TypeError on a non-ASCII str, which
    # would turn a hostile ?state=é into a 500.
    if not expected or not hmac.compare_digest(provided.encode(), expected.encode()):
        raise ApiError("validation", "Invalid or expired sign-in attempt", 400)
    if request.args.get("error") or not request.args.get("code"):
        return redirect("/settings?calendar=denied")

    try:
        refresh_token = calendar_service.exchange_code(current_app.config, request.args["code"])
    except ApiError:
        # A raw JSON error page in the middle of a browser redirect flow is a
        # dead end; send the user back to Settings with a message instead.
        return redirect("/settings?calendar=error")
    conn = get_db()
    calendar_repo.upsert_link(conn, current_user.id, refresh_token)
    calendar_service.forget_user(current_user.id)

    # Put the tasks that already exist on the calendar too, not only new ones.
    flags = read_feature_flags(current_app.config)
    pending = task_service.list_tasks(conn, user_id=current_user.id, status="pending", flags=flags)
    current_app.extensions["calendar_sync"].queue_backfill(pending, current_user.id)
    return redirect("/settings?calendar=connected")


@bp.get("/api/calendar/status")
@login_required
def status():
    available = calendar_service.is_configured(current_app.config)
    connected = available and calendar_repo.get_link(get_db(), current_user.id) is not None
    return jsonify({"available": available, "connected": connected}), 200


@bp.post("/api/calendar/disconnect")
@login_required
def disconnect():
    conn = get_db()
    link = calendar_repo.get_link(conn, current_user.id)
    if link is not None:
        event_ids = calendar_repo.list_event_ids(conn, current_user.id)
        refresh_token, user_id = link["refresh_token"], current_user.id
        calendar_repo.delete_link(conn, user_id)  # the UI shows "disconnected" at once
        calendar_service.forget_user(user_id)
        config = current_app.config
        dispatcher.submit(
            lambda: calendar_service.cleanup_events_and_revoke(
                config, user_id, refresh_token, event_ids
            )
        )
    return "", 204
