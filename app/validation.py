"""Shared input-validation helpers used across services.

JSON bodies can carry any JSON type for a field a client meant to be a
string (a number, bool, list, dict) — (value or "").strip() silently
crashes on those instead of rejecting them, so every string field from a
request body goes through require_str() first.
"""

from app.errors import ApiError


def require_str(value: object, field_name: str) -> str:
    """None means the field was omitted, so it becomes "". Any other
    non-string value is a malformed request, not a 0-length string."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ApiError("validation", f"{field_name} must be a string", 422)
    return value
