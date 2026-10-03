"""Phase 2: effort estimate + start-by time (FEATURE_ESTIMATES).

I10: start_by = due_at - estimate_hours * multiplier * (1 + buffer).
I12: risk = none (done/no start_by) | red (now >= start_by) |
amber (start_by within 24h) | green (otherwise).
I13: multiplier = exp((n * mean_log_ratio + 5 * ln(1.5)) / (n + 5)),
clamped to [MULTIPLIER_MIN, MULTIPLIER_MAX]; n=0 gives exactly 1.5.

start_by and risk both compute on every read rather than being stored —
I11's "recompute when due_at/estimate/multiplier changes" then falls out
for free: there is no stale persisted value to go out of date, the next
read is always correct for whatever the inputs currently are. This is also
what makes Adaptive Replanning (CLAUDE.md 2.5) nothing more than this same
calculation: a task that's past its start_by always shows that on the very
next read, with no separate recompute step to trigger.
"""

import math

from app import timeutil
from app.constants import (
    DEFAULT_MULTIPLIER,
    MULTIPLIER_MAX,
    MULTIPLIER_MIN,
    RISK_AMBER_WINDOW_HOURS,
    START_BY_BUFFER,
)

_LN_DEFAULT_MULTIPLIER = math.log(DEFAULT_MULTIPLIER)
# Risk levels worth surfacing on the "Do this now" card, most urgent first.
# green and none are never urgent enough to be "the one thing to do now".
_DO_THIS_NOW_RISK_RANK = {"red": 0, "amber": 1}


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


def compute_risk(status: str, start_by: str | None) -> str:
    """I12. Note the red boundary (now >= start_by) is non-strict, unlike
    I4's overdue boundary (due_at < now) — timeutil names each separately
    rather than one caller flipping the other's comparison around."""
    if status != "pending" or start_by is None:
        return "none"
    if timeutil.is_now_at_or_after(start_by):
        return "red"
    amber_from = timeutil.add_hours_iso(start_by, -RISK_AMBER_WINDOW_HOURS)
    if timeutil.is_now_at_or_after(amber_from):
        return "amber"
    return "green"


def pick_do_this_now(tasks: list[dict]) -> dict | None:
    """The single most urgent task: the earliest start_by among red-risk
    tasks, or failing that the earliest among amber; green/none tasks are
    never urgent enough to be "the one thing to do now". None if nothing
    qualifies."""
    candidates = [t for t in tasks if t["risk"] in _DO_THIS_NOW_RISK_RANK]
    if not candidates:
        return None
    return min(candidates, key=lambda t: (_DO_THIS_NOW_RISK_RANK[t["risk"]], t["start_by"]))
