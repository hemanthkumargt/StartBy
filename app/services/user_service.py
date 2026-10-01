"""Business rules for a user's own settings (dark mode, timezone)."""

import sqlite3
from zoneinfo import available_timezones

from app.errors import ApiError
from app.repositories import user_repo

_VALID_TIMEZONES = available_timezones()


def serialize_user(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "email": row["email"],
        "timezone": row["timezone"],
        "dark_mode": bool(row["dark_mode"]),
    }


def update_settings(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    dark_mode: bool | None = None,
    timezone: str | None = None,
) -> dict:
    if timezone is not None and timezone not in _VALID_TIMEZONES:
        raise ApiError("validation", f"Unknown timezone: {timezone}", 422)
    row = user_repo.update_settings(conn, user_id, dark_mode=dark_mode, timezone=timezone)
    if row is None:
        raise ApiError("not_found", "User not found", 404)
    return serialize_user(row)
