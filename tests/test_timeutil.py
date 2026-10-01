from datetime import datetime

from freezegun import freeze_time

from app.timeutil import local_to_utc_iso, parse_iso, to_iso, utc_iso_to_local, utcnow_iso


def test_I9_ist_evening_time_stores_as_utc_morning():
    """PRD invariant I9: all stored times are UTC; an IST user creating
    '5 PM' stores 11:30 UTC (IST is UTC+5:30)."""
    stored = local_to_utc_iso(datetime(2026, 10, 3, 17, 0, 0), "Asia/Kolkata")
    assert stored == "2026-10-03T11:30:00"


def test_utc_iso_to_local_round_trips_back_to_ist():
    local_dt = utc_iso_to_local("2026-10-03T11:30:00", "Asia/Kolkata")
    assert (local_dt.hour, local_dt.minute) == (17, 0)


@freeze_time("2026-10-01T12:00:00")
def test_utcnow_iso_is_frozen_for_tests():
    assert utcnow_iso() == "2026-10-01T12:00:00"


def test_to_iso_and_parse_iso_round_trip():
    original = datetime(2026, 1, 15, 9, 30, 0)
    assert parse_iso(to_iso(original)).strftime("%Y-%m-%dT%H:%M:%S") == "2026-01-15T09:30:00"
