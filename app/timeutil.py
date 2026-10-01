"""Single place for all time logic (PRD hard constraint).

All stored datetimes are UTC ISO-8601 strings. Display-side conversion to a
user's timezone happens only in templates/JS, never here. Routing every call
through this module lets tests freeze time with freezegun.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

UTC_FORMAT = "%Y-%m-%dT%H:%M:%S"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def utcnow_iso() -> str:
    return to_iso(utcnow())


def to_iso(dt: datetime) -> str:
    """Store as naive-looking UTC ISO string (no offset), matching SQLite's
    own datetime('now') format so string comparison sorts correctly."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.strftime(UTC_FORMAT)


def parse_iso(value: str) -> datetime:
    """Parse a stored UTC ISO string back into an aware UTC datetime."""
    dt = datetime.strptime(value[:19], UTC_FORMAT)
    return dt.replace(tzinfo=timezone.utc)


def local_to_utc_iso(local_dt: datetime, tz_name: str) -> str:
    """A naive datetime, interpreted in tz_name, converted to a stored UTC string."""
    aware = local_dt.replace(tzinfo=ZoneInfo(tz_name))
    return to_iso(aware)


def utc_iso_to_local(value: str, tz_name: str) -> datetime:
    return parse_iso(value).astimezone(ZoneInfo(tz_name))
