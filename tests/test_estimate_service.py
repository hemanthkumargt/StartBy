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
