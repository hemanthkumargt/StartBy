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
    dark_mode: object = None,
    timezone: object = None,
) -> dict:
    if dark_mode is not None and not isinstance(dark_mode, bool):
        raise ApiError("validation", "dark_mode must be true or false", 422)
    if timezone is not None and (not isinstance(timezone, str) or timezone not in _VALID_TIMEZONES):
        raise ApiError("validation", f"Unknown timezone: {timezone}", 422)

    row = user_repo.find_by_id(conn, user_id)
    if row is None:
        raise ApiError("not_found", "User not found", 404)

    # "Keep the existing value when a field is omitted" is a business
    # decision, so it's resolved here, not inside the repository.
    new_dark_mode = int(dark_mode) if dark_mode is not None else row["dark_mode"]
    new_timezone = timezone if timezone is not None else row["timezone"]

    updated_row = user_repo.update_settings(
        conn, user_id, dark_mode=new_dark_mode, timezone=new_timezone
    )
    return serialize_user(updated_row)
