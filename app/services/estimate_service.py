"""Phase 2: effort estimate + start-by time (FEATURE_ESTIMATES).

I10: start_by = due_at - estimate_hours * multiplier * (1 + buffer).
I13: multiplier = exp((n * mean_log_ratio + 5 * ln(1.5)) / (n + 5)),
clamped to [MULTIPLIER_MIN, MULTIPLIER_MAX]; n=0 gives exactly 1.5.

Both compute on every read rather than being stored — I11's "recompute
when due_at/estimate/multiplier changes" then falls out for free: there is
no stale persisted value to go out of date, the next read is always
correct for whatever the inputs currently are. This is also what makes
Adaptive Replanning (CLAUDE.md 2.5) nothing more than this same
calculation: a task that's past its start_by always shows that on the very
next read, with no separate recompute step to trigger.
"""

import math

from app import timeutil
from app.constants import DEFAULT_MULTIPLIER, MULTIPLIER_MAX, MULTIPLIER_MIN, START_BY_BUFFER

_LN_DEFAULT_MULTIPLIER = math.log(DEFAULT_MULTIPLIER)


def multiplier_from_history(n: int, mean_log_ratio: float) -> float:
    """n is the number of this user's completed tasks (same tag) with a
    recorded actual time; mean_log_ratio is the mean of
    ln(actual_hours / estimate_hours) over those. No history (n=0) returns
    exactly DEFAULT_MULTIPLIER — the formula's own neutral point, not a
    special-cased fallback."""
    raw = math.exp((n * mean_log_ratio + 5 * _LN_DEFAULT_MULTIPLIER) / (n + 5))
    return max(MULTIPLIER_MIN, min(MULTIPLIER_MAX, raw))


def compute_start_by(
    due_at: str | None, estimate_hours: float | None, multiplier: float
) -> str | None:
    """None if either input the calculation needs is missing."""
    if due_at is None or estimate_hours is None:
        return None
    lead_time_hours = estimate_hours * multiplier * (1 + START_BY_BUFFER)
    return timeutil.add_hours_iso(due_at, -lead_time_hours)
