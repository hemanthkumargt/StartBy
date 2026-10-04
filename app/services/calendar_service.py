"""Google Calendar sync (per-user OAuth, scope calendar.events).

A pending task with a deadline becomes a calendar block from its start_by
(or 30 minutes before a deadline-only task) to its due time. Edits patch the
same event; completing or deleting the task removes it. The OAuth refresh
token is stored per user in calendar_links; access tokens are minted on
demand and cached in memory.

Honest limits, by design: the app uses the narrow calendar.events scope, so
it can only touch events it created. While the Google OAuth consent screen
is in "Testing" mode only listed test users can connect and refresh tokens
expire after 7 days — a revoked/expired token disconnects the user cleanly
(they simply reconnect) rather than failing every later task edit."""

import base64
import hashlib
import logging
import sqlite3
import time
import urllib.parse
from datetime import datetime, timedelta
from typing import Any

from app import timeutil
from app.errors import ApiError
from app.gcp import dispatcher, rest
from app.repositories import calendar_repo

logger = logging.getLogger(__name__)

SCOPE = "https://www.googleapis.com/auth/calendar.events"
_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
_EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
_DEADLINE_ONLY_BLOCK = timedelta(minutes=30)
_MIN_BLOCK = timedelta(minutes=15)
MAX_BACKFILL = 50

# (user_id, hash of refresh token) -> (access token, expiry). Keyed by the token
# too, so a user who reconnects a DIFFERENT Google account never reuses the old
# account's cached access token (the other worker's cache is not cleared).
_token_cache: dict[tuple[int, str], tuple[str, float]] = {}


def is_configured(config: Any) -> bool:
    has_credentials = bool(config["GOOGLE_CLIENT_ID"] and config["GOOGLE_CLIENT_SECRET"])
    return has_credentials and bool(redirect_uri(config))


def redirect_uri(config: Any) -> str:
    if config["GOOGLE_REDIRECT_URI"]:
        return config["GOOGLE_REDIRECT_URI"]
    return f"{config['APP_BASE_URL']}/calendar/callback" if config["APP_BASE_URL"] else ""


def authorization_url(config: Any, state: str) -> str:
    query = urllib.parse.urlencode(
        {
            "client_id": config["GOOGLE_CLIENT_ID"],
            "redirect_uri": redirect_uri(config),
            "response_type": "code",
            "scope": SCOPE,
            # offline + consent: guarantees Google returns a refresh token
            # even if this user connected before and then disconnected.
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
    )
    return f"{_AUTH_URL}?{query}"


def _form(fields: dict[str, str]) -> bytes:
    return urllib.parse.urlencode(fields).encode()


def exchange_code(config: Any, code: str) -> str:
    """Authorization code -> refresh token."""
    try:
        payload = rest.request_json(
            "POST",
            _TOKEN_URL,
            raw_body=_form(
                {
                    "code": code,
                    "client_id": config["GOOGLE_CLIENT_ID"],
                    "client_secret": config["GOOGLE_CLIENT_SECRET"],
                    "redirect_uri": redirect_uri(config),
                    "grant_type": "authorization_code",
                }
            ),
            content_type="application/x-www-form-urlencoded",
            use_auth=False,
        )
    except rest.GcpError as exc:
        raise ApiError("upstream_error", "Google rejected the sign-in; try again", 502) from exc
    token = payload.get("refresh_token")
    if not token:
        raise ApiError("upstream_error", "Google did not grant offline access", 502)
    return token


class CalendarAuthError(Exception):
    """The stored refresh token no longer works (revoked, expired, deleted):
    Google said invalid_grant."""


class CalendarUnavailableError(Exception):
    """The token endpoint refused us for a reason that is NOT the user's grant
    (invalid_client, invalid_request, ...: our own OAuth client config is wrong
    or Google is unhappy). The user's link is kept; fix the config and sync
    resumes."""


# Calendar answers 403 + one of these reasons when a per-user or per-project
# quota is hit; it clears within seconds, so one delayed retry is worthwhile.
_RATE_LIMIT_REASONS = frozenset({"rateLimitExceeded", "userRateLimitExceeded"})
RATE_LIMIT_BACKOFF_SECONDS = 2.0


def _calendar_request(method: str, url: str, **kwargs: Any) -> dict:
    """rest.request_json for a Calendar call, retried once (after a backoff)
    on a rate-limit 403."""
    try:
        return rest.request_json(method, url, **kwargs)
    except rest.GcpError as exc:
        if exc.status != 403 or exc.error not in _RATE_LIMIT_REASONS:
            raise
        logger.warning("calendar_rate_limited method=%s reason=%s", method, exc.error)
        time.sleep(RATE_LIMIT_BACKOFF_SECONDS)
        return rest.request_json(method, url, **kwargs)


def _access_token(config: Any, user_id: int, refresh_token: str) -> str:
    cache_key = (user_id, hashlib.sha256(refresh_token.encode()).hexdigest()[:16])
    cached = _token_cache.get(cache_key)
    if cached and timeutil.utcnow().timestamp() < cached[1] - 60:
        return cached[0]
    try:
        payload = rest.request_json(
            "POST",
            _TOKEN_URL,
            raw_body=_form(
                {
                    "client_id": config["GOOGLE_CLIENT_ID"],
                    "client_secret": config["GOOGLE_CLIENT_SECRET"],
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                }
            ),
            content_type="application/x-www-form-urlencoded",
            use_auth=False,
        )
    except rest.GcpError as exc:
        if exc.status in (400, 401):
            if exc.error == "invalid_grant":
                raise CalendarAuthError(str(exc)) from exc
            logger.error(
                "calendar_token_refused status=%s error=%s (link kept; check the "
                "Google OAuth client settings)",
                exc.status,
                exc.error or "unknown",
            )
            raise CalendarUnavailableError(str(exc)) from exc
        raise
    token = payload["access_token"]
    _token_cache[cache_key] = (
        token,
        timeutil.utcnow().timestamp() + float(payload.get("expires_in", 3600)),
    )
    return token


def revoke(refresh_token: str) -> None:
    """Best-effort: tell Google to drop the grant. Never raises."""
    try:
        rest.request_json(
            "POST",
            _REVOKE_URL,
            raw_body=_form({"token": refresh_token}),
            content_type="application/x-www-form-urlencoded",
            use_auth=False,
        )
    except rest.GcpError as exc:
        logger.warning("calendar_revoke_failed error=%s", exc)


def forget_user(user_id: int) -> None:
    for key in [k for k in _token_cache if k[0] == user_id]:
        del _token_cache[key]


def event_id_for(user_id: int, task_id: int) -> str:
    """Deterministic Google event id (base32hex: a-v, 0-9, 5-1024 chars). Two
    workers, a retried POST, or a reconnect all address the SAME event instead
    of creating look-alikes."""
    digest = hashlib.sha256(f"startby:{user_id}:{task_id}".encode()).digest()
    return base64.b32hexencode(digest).decode().rstrip("=").lower()[:26]


def _rfc3339(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def event_body(task: dict[str, Any]) -> dict[str, Any]:
    due = timeutil.parse_iso(task["due_at"])
    start_by = task.get("start_by")
    start = timeutil.parse_iso(start_by) if start_by else None
    if start is None or start >= due:
        start = due - _DEADLINE_ONLY_BLOCK
    end = max(due, start + _MIN_BLOCK)
    description = "Planned by StartBy."
    if task.get("start_by_explanation"):
        description += f"\n\n{task['start_by_explanation']}"
    return {
        "summary": f"Work on: {task['title']}",
        "description": description,
        "start": {"dateTime": _rfc3339(start)},
        "end": {"dateTime": _rfc3339(end)},
        "reminders": {"useDefault": True},
    }


class CalendarSync:
    """hooks listener: mirrors task events into each connected user's calendar
    on the dispatcher thread, with its own SQLite connection (the request's
    connection is not available, or safe to share, off-thread)."""

    def __init__(self, config: Any) -> None:
        self._config = config

    def _enabled(self) -> bool:
        return is_configured(self._config)

    def on_task_created(self, task: dict[str, Any], *, user_id: int) -> None:
        self._queue(task, user_id)

    def on_task_updated(
        self, task: dict[str, Any], changed_fields: list[str], *, user_id: int
    ) -> None:
        self._queue(task, user_id)

    def on_task_completed(self, task: dict[str, Any], *, user_id: int) -> None:
        self._queue(task, user_id)

    def on_task_reopened(self, task: dict[str, Any], *, user_id: int) -> None:
        self._queue(task, user_id)

    def on_task_deleted(self, task_id: int, *, user_id: int) -> None:
        self._queue({"id": task_id, "status": "deleted"}, user_id)

    def queue_backfill(self, tasks: list[dict[str, Any]], user_id: int) -> None:
        if len(tasks) > MAX_BACKFILL:
            logger.warning(
                "calendar_backfill_capped user_id=%s total=%s cap=%s",
                user_id,
                len(tasks),
                MAX_BACKFILL,
            )
        for task in tasks[:MAX_BACKFILL]:
            self._queue(task, user_id)

    def _queue(self, task: dict[str, Any], user_id: int) -> None:
        if not self._enabled():
            return
        dispatcher.submit(lambda: self._sync(task, user_id))

    def _sync(self, task: dict[str, Any], user_id: int) -> None:
        conn = sqlite3.connect(self._config["DATABASE_PATH"], timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            link = calendar_repo.get_link(conn, user_id)
            if link is None:
                return
            existing = calendar_repo.get_event(conn, task["id"])
            wanted = task.get("status") == "pending" and bool(task.get("due_at"))
            if not wanted and existing is None:
                return  # nothing on the calendar and nothing to add: skip the token call
            try:
                token = _access_token(self._config, user_id, link["refresh_token"])
                self._apply(conn, token, task, user_id, existing, wanted)
            except CalendarAuthError:
                logger.warning("calendar_token_revoked user_id=%s", user_id)
                calendar_repo.delete_link(conn, user_id)
                forget_user(user_id)
            except CalendarUnavailableError:
                return  # logged at error level; the user's link is untouched
            except sqlite3.IntegrityError:
                # The task/user vanished between queueing and running (foreign
                # keys are enforced here too): nothing to map, nothing to do.
                logger.warning("calendar_task_gone task_id=%s", task["id"])
        finally:
            conn.close()

    def _apply(
        self,
        conn: sqlite3.Connection,
        token: str,
        task: dict[str, Any],
        user_id: int,
        existing: sqlite3.Row | None,
        wanted: bool,
    ) -> None:
        if not wanted:
            if existing is not None:
                self._delete_event(token, existing["event_id"])
                calendar_repo.delete_event(conn, task["id"])
            return

        body = event_body(task)
        event_id = event_id_for(user_id, task["id"])
        if existing is not None:
            try:
                # status=confirmed also revives an event the user (or we) deleted
                _calendar_request(
                    "PATCH",
                    f"{_EVENTS_URL}/{event_id}",
                    body={**body, "status": "confirmed"},
                    bearer=token,
                )
                return
            except rest.GcpError as exc:
                if exc.status not in (404, 410):
                    raise
        try:
            _calendar_request("POST", _EVENTS_URL, body={**body, "id": event_id}, bearer=token)
        except rest.GcpError as exc:
            if exc.status != 409:
                raise
            # The id exists already (a racing worker, a retried POST, or a
            # cancelled event from before a reconnect): update it instead.
            _calendar_request(
                "PATCH",
                f"{_EVENTS_URL}/{event_id}",
                body={**body, "status": "confirmed"},
                bearer=token,
            )
        calendar_repo.upsert_event(conn, task["id"], user_id, event_id)

    @staticmethod
    def _delete_event(token: str, event_id: str) -> None:
        try:
            _calendar_request(
                "DELETE", f"{_EVENTS_URL}/{urllib.parse.quote(event_id)}", bearer=token
            )
        except rest.GcpError as exc:
            if exc.status not in (404, 410):  # already gone is the goal state
                raise


def cleanup_events_and_revoke(
    config: Any, user_id: int, refresh_token: str, event_ids: list[str]
) -> None:
    """Disconnect: remove the events StartBy put on the calendar while the
    token is still good (afterwards nothing could), then revoke the grant.
    Best-effort and run off-thread; a failure leaves events behind, never an
    error for the user."""
    try:
        token = _access_token(config, user_id, refresh_token)
        for event_id in event_ids:
            try:
                CalendarSync._delete_event(token, event_id)
            except rest.GcpError as exc:
                logger.warning("calendar_cleanup_failed event=%s error=%s", event_id, exc)
    except (CalendarAuthError, CalendarUnavailableError, rest.GcpError) as exc:
        logger.warning("calendar_cleanup_skipped user_id=%s error=%s", user_id, exc)
    finally:
        revoke(refresh_token)
        forget_user(user_id)
