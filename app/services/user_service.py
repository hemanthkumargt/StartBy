"""Business rules for a user's own settings (dark mode, timezone)."""

import sqlite3
import unicodedata
from zoneinfo import available_timezones

from app.errors import ApiError
from app.repositories import user_repo

_VALID_TIMEZONES = available_timezones()
_UNSET: object = object()  # "field not sent" (None means "clear it")

ASSISTANT_NAME_MAX = 30
_ASSISTANT_NAME_PUNCT = " .'-"


def _name_chars_ok(name: str) -> bool:
    """Letters and digits of any script, their combining marks (Devanagari matras,
    accents) and a little punctuation: it is read aloud and shown in the page, so no
    markup or control characters. (\\w is not enough: it rejects combining marks.)"""
    if not name[0].isalnum():
        return False
    return all(
        c.isalnum() or c in _ASSISTANT_NAME_PUNCT or unicodedata.category(c).startswith("M")
        for c in name
    )


def validate_assistant_name(value: object) -> str | None:
    """None or "" clears the custom name (back to the site default)."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ApiError("validation", "assistant_name must be text", 422)
    name = " ".join(value.split())
    if not name:
        return None
    if len(name) > ASSISTANT_NAME_MAX:
        raise ApiError(
            "validation",
            f"The assistant's name must be at most {ASSISTANT_NAME_MAX} characters",
            422,
        )
    if not _name_chars_ok(name):
        raise ApiError(
            "validation",
            "Use letters, numbers, spaces, apostrophes, dots or hyphens in the name",
            422,
        )
    return name


def serialize_user(row: sqlite3.Row, *, include_assistant_name: bool = True) -> dict:
    data = {
        "id": row["id"],
        "name": row["name"],
        "email": row["email"],
        "timezone": row["timezone"],
        "dark_mode": bool(row["dark_mode"]),
    }
    if include_assistant_name:
        data["assistant_name"] = row["assistant_name"]
    return data


def update_settings(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    dark_mode: object = None,
    timezone: object = None,
    assistant_name: object = _UNSET,
    include_assistant_name: bool = True,
) -> dict:
    if dark_mode is not None and not isinstance(dark_mode, bool):
        raise ApiError("validation", "dark_mode must be true or false", 422)
    if timezone is not None and (not isinstance(timezone, str) or timezone not in _VALID_TIMEZONES):
        raise ApiError("validation", f"Unknown timezone: {timezone}", 422)

    new_assistant_name = _UNSET
    if assistant_name is not _UNSET:
        new_assistant_name = validate_assistant_name(assistant_name)

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
    if new_assistant_name is not _UNSET:
        updated_row = user_repo.update_assistant_name(conn, user_id, new_assistant_name)
    return serialize_user(updated_row, include_assistant_name=include_assistant_name)
