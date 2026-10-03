import pytest
from freezegun import freeze_time

from app.constants import MULTIPLIER_MAX, MULTIPLIER_MIN
from app.services import estimate_service


def test_I13_no_history_gives_exactly_default_multiplier():
    assert estimate_service.multiplier_from_history(0, 0.0) == 1.5


def test_I13_multiplier_clamps_to_upper_bound():
    # A large positive mean_log_ratio (user consistently takes far longer
    # than estimated) must never push the multiplier above the cap.
    result = estimate_service.multiplier_from_history(50, 5.0)
    assert result == MULTIPLIER_MAX


def test_I13_multiplier_clamps_to_lower_bound():
    # A large negative mean_log_ratio (user consistently finishes faster
    # than estimated) must never push the multiplier below the floor.
    result = estimate_service.multiplier_from_history(50, -5.0)
    assert result == MULTIPLIER_MIN


def test_I10_start_by_is_none_without_a_due_date():
    assert estimate_service.compute_start_by(None, 2.0, 1.5) is None


def test_I10_start_by_is_none_without_an_estimate():
    assert estimate_service.compute_start_by("2026-10-10T18:00:00", None, 1.5) is None


def test_I10_start_by_worked_example():
    # 2.0h estimate * 1.5 multiplier * 1.15 (15% buffer) = 3.45h = 3h27m
    # lead time before the 18:00:00 due date.
    result = estimate_service.compute_start_by("2026-10-10T18:00:00", 2.0, 1.5)
    assert result == "2026-10-10T14:33:00"


def test_I12_risk_is_none_for_a_done_task():
    assert estimate_service.compute_risk("done", "2026-10-10T14:33:00") == "none"


def test_I12_risk_is_none_without_a_start_by():
    assert estimate_service.compute_risk("pending", None) == "none"


def test_I12_risk_is_red_when_now_equals_start_by():
    # I12's boundary is non-strict ("now >= start_by"), unlike I4's overdue
    # boundary (due_at < now) — exact equality must already be red.
    with freeze_time("2026-10-10T14:33:00"):
        assert estimate_service.compute_risk("pending", "2026-10-10T14:33:00") == "red"


def test_I12_risk_is_red_when_start_by_has_passed():
    with freeze_time("2026-10-10T15:00:00"):
        assert estimate_service.compute_risk("pending", "2026-10-10T14:33:00") == "red"


def test_I12_risk_is_amber_within_24_hours_of_start_by():
    with freeze_time("2026-10-09T15:00:00"):
        assert estimate_service.compute_risk("pending", "2026-10-10T14:33:00") == "amber"


def test_I12_risk_is_green_more_than_24_hours_before_start_by():
    with freeze_time("2026-10-08T00:00:00"):
        assert estimate_service.compute_risk("pending", "2026-10-10T14:33:00") == "green"


def test_pick_do_this_now_prefers_red_over_amber():
    tasks = [
        {"id": 1, "risk": "amber", "start_by": "2026-10-10T10:00:00"},
        {"id": 2, "risk": "red", "start_by": "2026-10-10T12:00:00"},
    ]
    assert estimate_service.pick_do_this_now(tasks)["id"] == 2


def test_pick_do_this_now_picks_earliest_start_by_among_same_risk():
    tasks = [
        {"id": 1, "risk": "red", "start_by": "2026-10-10T12:00:00"},
        {"id": 2, "risk": "red", "start_by": "2026-10-10T08:00:00"},
    ]
    assert estimate_service.pick_do_this_now(tasks)["id"] == 2


def test_pick_do_this_now_is_none_when_nothing_is_urgent():
    tasks = [
        {"id": 1, "risk": "green", "start_by": "2026-10-20T00:00:00"},
        {"id": 2, "risk": "none", "start_by": None},
    ]
    assert estimate_service.pick_do_this_now(tasks) is None


def test_pick_do_this_now_is_none_for_an_empty_list():
    assert estimate_service.pick_do_this_now([]) is None


def test_I13_multipliers_by_tag_worked_example():
    # PRD's own worked example: 3 completed "study" tasks at actual/estimate
    # ratios 2.0, 2.5, 2.0 -> multiplier 1.72.
    rows = [
        {"tag": "study", "estimate_hours": 1.0, "actual_hours": 2.0},
        {"tag": "study", "estimate_hours": 2.0, "actual_hours": 5.0},
        {"tag": "study", "estimate_hours": 3.0, "actual_hours": 6.0},
    ]
    result = estimate_service.multipliers_by_tag(rows)
    assert result["study"] == pytest.approx(1.72, abs=0.01)


def test_multipliers_by_tag_has_no_key_for_a_tag_with_no_history():
    assert estimate_service.multipliers_by_tag([]) == {}


def test_multipliers_by_tag_keeps_tags_independent():
    rows = [
        {"tag": "work", "estimate_hours": 2.0, "actual_hours": 2.0},  # ratio 1.0
        {"tag": "personal", "estimate_hours": 2.0, "actual_hours": 4.0},  # ratio 2.0
    ]
    result = estimate_service.multipliers_by_tag(rows)
    assert result["work"] != result["personal"]
    assert set(result.keys()) == {"work", "personal"}
