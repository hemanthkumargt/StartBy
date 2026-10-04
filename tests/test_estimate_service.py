import pytest
from freezegun import freeze_time

from app.constants import DEFAULT_MULTIPLIER, MULTIPLIER_MAX, MULTIPLIER_MIN
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


def test_no_history_fallback_matches_multiplier_from_history_at_n_zero():
    """Pins the equivalence task_service._multipliers_for and
    reminder_service rely on: a tag with no history falls back to the
    plain constant DEFAULT_MULTIPLIER (skipping multiplier_from_history
    entirely, as an optimization) rather than calling
    multiplier_from_history(0, 0.0) and clamping. That's only safe because
    the two are identical today — if DEFAULT_MULTIPLIER is ever changed to
    a value outside [MULTIPLIER_MIN, MULTIPLIER_MAX], this test fails
    instead of the two silently diverging."""
    assert DEFAULT_MULTIPLIER == estimate_service.multiplier_from_history(0, 0.0)


def test_explain_start_by_cold_start_says_so_and_matches_the_i10_worked_example():
    # Same numbers as test_I10_start_by_worked_example: 2h x 1.5 x 1.15 = 3h27m.
    text = estimate_service.explain_start_by(2.0, 1.5, tag="study", learned=False)
    assert text == (
        "You estimated 2h. You have no completed study tasks yet, so we assume 1.50x "
        "until we learn your pace and plan for 3h, plus a 15% buffer, which is 3h 27m. "
        "Start that long before the due time."
    )


def test_explain_start_by_learned_multiplier_credits_the_users_own_history():
    text = estimate_service.explain_start_by(2.0, 1.718134, tag="study", learned=True)
    assert "Your completed study tasks suggest planning for about 1.72x your estimates" in text
    assert "which is 3h 57m" in text


def test_explain_start_by_formats_sub_hour_amounts_in_minutes():
    text = estimate_service.explain_start_by(0.25, 1.0, tag="work", learned=True)
    assert text.startswith("You estimated 15m.")
    assert "which is 17m" in text


# ---- Adaptive Replanning -------------------------------------------------


def test_replan_after_missed_start_says_start_now_and_how_late_it_will_finish():
    from freezegun import freeze_time

    from app.services import estimate_service

    # 3.5h of planned work, due 10:00 -> start_by was 06:30; it is now 08:00.
    with freeze_time("2026-10-04T08:00:00"):
        replan = estimate_service.compute_replan("2026-10-04T10:00:00", "2026-10-04T06:30:00")
    assert replan == {
        "start_at": "2026-10-04T08:00:00",
        "projected_finish": "2026-10-04T11:30:00",
        "late_by_hours": 1.04,
    }


def test_replan_right_at_start_by_is_not_late():
    from freezegun import freeze_time

    from app.services import estimate_service

    with freeze_time("2026-10-04T06:30:00"):
        replan = estimate_service.compute_replan("2026-10-04T10:00:00", "2026-10-04T06:30:00")
    assert replan["late_by_hours"] == 0
    assert "still finish before" in estimate_service.describe_replan(replan, 3.5)


def test_describe_replan_mentions_extension_when_late():
    from app.services import estimate_service

    text = estimate_service.describe_replan(
        {"start_at": "x", "projected_finish": "y", "late_by_hours": 1.5}, 3.5
    )
    assert "3h 30m" in text and "1h 30m after the due time" in text and "extension" in text
