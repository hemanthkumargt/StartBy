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
import sqlite3
from collections.abc import Iterable

from app import timeutil
from app.constants import (
    DEFAULT_MULTIPLIER,
    MAX_ESTIMATE_HOURS,
    MULTIPLIER_MAX,
    MULTIPLIER_MIN,
    RATIO_CLAMP_MAX,
    RATIO_CLAMP_MIN,
    REPLAN_LATE_NOISE_HOURS,
    RISK_AMBER_WINDOW_HOURS,
    START_BY_BUFFER,
)

_LN_DEFAULT_MULTIPLIER = math.log(DEFAULT_MULTIPLIER)
# Risk levels worth surfacing on the "Do this now" card, most urgent first.
# green and none are never urgent enough to be "the one thing to do now".
_DO_THIS_NOW_RISK_RANK = {"red": 0, "amber": 1}
# The longest lead time compute_start_by can ever produce (max estimate x
# max multiplier x buffer) — a task due further out than this can't be red
# yet however its own estimate/multiplier work out. Lets a caller scanning
# for "could this be red" (e.g. the start-now reminder cron) bound its
# search in SQL instead of fetching and discarding every far-future task.
MAX_LEAD_TIME_HOURS = MAX_ESTIMATE_HOURS * MULTIPLIER_MAX * (1 + START_BY_BUFFER)


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
    try:
        return timeutil.add_hours_iso(due_at, -lead_time_hours)
    except OverflowError:
        # A deadline at the very edge of the calendar: no start time rather
        # than a crash that takes the whole list (and the reminder job) down.
        return None


def compute_replan(due_at: str, start_by: str) -> dict:
    """Adaptive Replanning (CLAUDE.md 2.5) for a task already past its
    start_by: the original schedule is gone, so recommend the new one —
    start right now, and say honestly when the work can no longer finish by
    the deadline. Computed fresh on every read like start_by itself (I11),
    so the recommendation keeps moving as time passes."""
    lead = timeutil.parse_iso(due_at) - timeutil.parse_iso(start_by)
    now = timeutil.utcnow()
    finish = now + lead
    # "Late" is measured against the work itself, not the 15% safety buffer:
    # a job with 6h of real work and 6.4h left is not late, it has eaten buffer.
    work = lead / (1 + START_BY_BUFFER)
    late_hours = (now + work - timeutil.parse_iso(due_at)).total_seconds() / 3600
    late_hours = late_hours if late_hours >= REPLAN_LATE_NOISE_HOURS else 0.0
    return {
        "start_at": timeutil.to_iso(now),
        "projected_finish": timeutil.to_iso(finish),
        "late_by_hours": round(late_hours, 2),
    }


def describe_replan(replan: dict, lead_hours: float) -> str:
    """Plain-language replan for the reminder email (no clock times: the
    server doesn't format in the user's timezone)."""
    work = f"At your pace this takes about {format_hours(lead_hours)}, so start now."
    if replan["late_by_hours"] > 0:
        return (
            f"{work} You have already missed the planned start, so it will finish about "
            f"{format_hours(replan['late_by_hours'])} after the due time — consider asking "
            "for an extension or moving the deadline."
        )
    return f"{work} You can still finish before the due time."


def format_hours(hours: float) -> str:
    total_minutes = round(hours * 60)
    whole_hours, minutes = divmod(total_minutes, 60)
    if whole_hours and minutes:
        return f"{whole_hours}h {minutes}m"
    if whole_hours:
        return f"{whole_hours}h"
    return f"{minutes}m"


def explain_start_by(estimate_hours: float, multiplier: float, *, tag: str, learned: bool) -> str:
    """Plain-language version of I10, for anywhere a user asks "why this
    start time?" — the dashboard card and the start-now reminder email both
    use this one function so they can't describe the calculation
    differently. `learned` is whether the multiplier came from the user's
    own completed tasks of this tag (I13) rather than the cold-start
    default."""
    planned_hours = estimate_hours * multiplier
    lead_time_hours = planned_hours * (1 + START_BY_BUFFER)
    planned = format_hours(planned_hours)
    if learned:
        # The learned figure is blended with the 1.5x starting assumption until
        # there is plenty of history, so it is a planning factor, not an average
        # of what happened — don't call it "have taken".
        basis = (
            f"Your completed {tag} tasks suggest planning for about {multiplier:.2f}x your "
            f"estimates, so we plan for {planned}"
        )
    else:
        basis = (
            f"You have no completed {tag} tasks yet, so we assume {multiplier:.2f}x "
            f"until we learn your pace and plan for {planned}"
        )
    return (
        f"You estimated {format_hours(estimate_hours)}. {basis}, "
        f"plus a {round(START_BY_BUFFER * 100)}% buffer, "
        f"which is {format_hours(lead_time_hours)}. Start that long before the due time."
    )


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


def multipliers_by_tag(rows: Iterable[sqlite3.Row]) -> dict[str, float]:
    """I13, per tag. rows: each with tag/estimate_hours/actual_hours
    (task_repo.estimate_actual_pairs_for_user's shape) — one query per
    request rather than one per task, since every task of the same tag
    would otherwise redo the identical history lookup. A tag with no
    history simply isn't a key here; callers fall back to
    DEFAULT_MULTIPLIER, which is exactly what multiplier_from_history(0,
    0.0) would have returned anyway."""
    log_ratios_by_tag: dict[str, list[float]] = {}
    for row in rows:
        ratio = row["actual_hours"] / row["estimate_hours"]
        ratio = max(RATIO_CLAMP_MIN, min(RATIO_CLAMP_MAX, ratio))  # one typo != your pace
        log_ratios_by_tag.setdefault(row["tag"], []).append(math.log(ratio))
    return {
        tag: multiplier_from_history(len(ratios), sum(ratios) / len(ratios))
        for tag, ratios in log_ratios_by_tag.items()
    }


def pick_do_this_now(tasks: list[dict]) -> dict | None:
    """The single most urgent task: the earliest start_by among red-risk
    tasks, or failing that the earliest among amber; green/none tasks are
    never urgent enough to be "the one thing to do now". None if nothing
    qualifies."""
    candidates = [t for t in tasks if t["risk"] in _DO_THIS_NOW_RISK_RANK]
    if not candidates:
        return None
    # Tasks that can still be met come before ones already past their deadline,
    # so a task abandoned weeks ago never outranks one due in half an hour.
    return min(
        candidates,
        key=lambda t: (
            t.get("is_overdue", False),
            _DO_THIS_NOW_RISK_RANK[t["risk"]],
            t["start_by"],
        ),
    )
