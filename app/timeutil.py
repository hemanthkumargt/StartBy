"""Single place for all time logic (PRD hard constraint).

All stored datetimes are UTC ISO-8601 strings. Display-side conversion to a
user's timezone happens only in templates/JS, never here. Routing every call
through this module lets tests freeze time with freezegun.
"""

from datetime import datetime, timedelta, timezone
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


def normalize_due_at(value: str) -> str:
    """Accept an ISO-8601 string (with or without an offset, 'Z' included)
    from the API and return it as a stored UTC ISO string. A naive string
    with no offset is assumed to already be UTC. Raises ValueError if it
    cannot be parsed."""
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    dt = datetime.fromisoformat(v)
    return to_iso(dt)


def is_before_now(iso_value: str) -> bool:
    """String comparison is safe here: to_iso always produces a fixed-width
    zero-padded 'YYYY-MM-DDTHH:MM:SS', which sorts identically to its
    chronological order."""
    return iso_value < utcnow_iso()


def add_hours_iso(iso_value: str, hours: float) -> str:
    return to_iso(parse_iso(iso_value) + timedelta(hours=hours))
