"""Phase 2 insights (FEATURE_INSIGHTS): the overload warning and the
estimation report card. Both are computed on read from the same tasks and
the same per-tag multipliers the rest of Phase 2 uses — nothing is stored
(I11), so they can never disagree with the risk badges."""

import math
import sqlite3

from app import timeutil
from app.constants import (
    OVERLOAD_CRITICAL_RED,
    OVERLOAD_WARNING_RED,
    OVERLOAD_WARNING_RED_PLUS_AMBER,
    RATIO_CLAMP_MAX,
    RATIO_CLAMP_MIN,
    REPORT_MIN_SAMPLES_FOR_SUMMARY,
    REPORT_MIN_SAMPLES_FOR_TREND,
    REPORT_ON_TARGET_BAND,
    REPORT_SERIES_LIMIT,
    REPORT_TREND_MIN_CHANGE,
    STALE_OVERDUE_DAYS,
)
from app.repositories import task_repo
from app.services import estimate_service, task_service

_MAX_LISTED_TASKS = 3


def _lead_hours(task: dict) -> float:
    """Hours between a task's start_by and due_at — i.e. the planned work
    (estimate x multiplier x buffer) that has to fit before the deadline."""
    start = timeutil.parse_iso(task["start_by"])
    due = timeutil.parse_iso(task["due_at"])
    return (due - start).total_seconds() / 3600


def overload_level(red: int, amber: int) -> str:
    if red >= OVERLOAD_CRITICAL_RED:
        return "critical"
    if red >= OVERLOAD_WARNING_RED or red + amber >= OVERLOAD_WARNING_RED_PLUS_AMBER:
        return "warning"
    return "none"


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _overload_message(level: str, red: int, amber: int, hours: float) -> str:
    if level == "none":
        return "Your workload looks manageable."
    stacked = f"{plural(red, 'task')} past their start time"
    if amber:
        stacked += f" and {amber} more starting within 24 hours"
    work = f"about {estimate_service.format_hours(hours)} of planned work"
    if level == "critical":
        return f"Overloaded: {stacked} — {work}. Move a deadline or drop something now."
    return f"Heads up: {stacked} — {work}. Start the reddest one first."


def is_abandoned(task: dict) -> bool:
    """Overdue for more than a week: a forgotten task, not current workload."""
    due = task.get("due_at")
    if not due:
        return False
    cutoff = timeutil.add_hours_iso(timeutil.utcnow_iso(), -24 * STALE_OVERDUE_DAYS)
    return due < cutoff


def build_overload(pending_tasks: list[dict]) -> dict:
    at_risk = [
        t
        for t in pending_tasks
        if t.get("risk") in ("red", "amber") and t.get("start_by") and not is_abandoned(t)
    ]
    red = [t for t in at_risk if t["risk"] == "red"]
    amber = [t for t in at_risk if t["risk"] == "amber"]
    level = overload_level(len(red), len(amber))
    hours = sum(_lead_hours(t) for t in at_risk)
    worst_first = sorted(at_risk, key=lambda t: (t["risk"] != "red", t["start_by"]))
    return {
        "level": level,
        "red": len(red),
        "amber": len(amber),
        "hours_at_risk": round(hours, 1),
        "message": _overload_message(level, len(red), len(amber), hours),
        "top_tasks": [
            {"id": t["id"], "title": t["title"], "risk": t["risk"]}
            for t in worst_first[:_MAX_LISTED_TASKS]
        ],
    }


def _geomean_ratio(rows: list[dict]) -> float | None:
    if not rows:
        return None
    return math.exp(sum(math.log(r["ratio"]) for r in rows) / len(rows))


def _trend(rows: list[dict]) -> dict:
    if len(rows) < REPORT_MIN_SAMPLES_FOR_TREND:
        return {"direction": "insufficient", "recent_ratio": None, "previous_ratio": None}
    half = len(rows) // 2
    previous, recent = _geomean_ratio(rows[:half]), _geomean_ratio(rows[half:])
    change = abs(math.log(recent)) - abs(math.log(previous))
    if change < -REPORT_TREND_MIN_CHANGE:
        direction = "improving"
    elif change > REPORT_TREND_MIN_CHANGE:
        direction = "worsening"
    else:
        direction = "steady"
    return {
        "direction": direction,
        "recent_ratio": round(recent, 2),
        "previous_ratio": round(previous, 2),
    }


def _summary(overall: float | None, samples: int) -> str:
    if overall is not None and samples < REPORT_MIN_SAMPLES_FOR_SUMMARY:
        return (
            f"{samples} finished task{'s' if samples != 1 else ''} with logged hours so far — "
            "not enough to say how you estimate yet (the planner adapts as you log more)."
        )
    if overall is None:
        return (
            "Finish tasks that have an estimate and log the actual hours "
            "to see how well you estimate."
        )
    if overall > 1 + REPORT_ON_TARGET_BAND:
        return f"Your tasks take about {overall:.2f}x your estimates — you tend to underestimate."
    if overall < 1 - REPORT_ON_TARGET_BAND:
        return f"Your tasks take about {overall:.2f}x your estimates — you tend to overestimate."
    return f"Your tasks take about {overall:.2f}x your estimates — your estimates are on target."


def build_report_card(history: list[sqlite3.Row], multipliers: dict[str, float]) -> dict:
    rows = [
        {
            "title": h["title"],
            "tag": h["tag"],
            "estimate_hours": h["estimate_hours"],
            "actual_hours": h["actual_hours"],
            "completed_at": h["completed_at"],
            # clamped like the planner's own learning, so one typo (2 -> 20) does
            # not turn the report into "you take 10x your estimates"
            "ratio": max(
                RATIO_CLAMP_MIN, min(RATIO_CLAMP_MAX, h["actual_hours"] / h["estimate_hours"])
            ),
        }
        for h in history
    ]
    overall = _geomean_ratio(rows)
    by_tag = []
    for tag in sorted({r["tag"] for r in rows}):
        tag_rows = [r for r in rows if r["tag"] == tag]
        by_tag.append(
            {
                "tag": tag,
                "samples": len(tag_rows),
                "avg_ratio": round(_geomean_ratio(tag_rows), 2),
                "multiplier": round(multipliers[tag], 2) if tag in multipliers else None,
            }
        )
    return {
        "samples": len(rows),
        "overall_ratio": round(overall, 2) if overall is not None else None,
        "summary": _summary(overall, len(rows)),
        "by_tag": by_tag,
        "trend": _trend(rows),
        "series": [
            {k: r[k] for k in ("title", "tag", "estimate_hours", "actual_hours", "completed_at")}
            | {"ratio": round(r["ratio"], 2)}
            for r in rows[-REPORT_SERIES_LIMIT:]
        ],
    }


_ESTIMATES_OFF = "Turn on effort estimates (FEATURE_ESTIMATES) to see this."


def get_insights(conn: sqlite3.Connection, *, user_id: int, flags: dict) -> dict:
    if not flags.get("estimates", False):
        # Without estimates there is no start_by/risk and no recorded actual hours:
        # saying "workload manageable" would be a confident answer about nothing.
        return {
            "overload": {
                "level": "none",
                "red": 0,
                "amber": 0,
                "hours_at_risk": 0.0,
                "message": _ESTIMATES_OFF,
                "top_tasks": [],
            },
            "report_card": build_report_card([], {}) | {"summary": _ESTIMATES_OFF},
        }
    pending = task_service.list_tasks(conn, user_id=user_id, status="pending", flags=flags)
    multipliers = estimate_service.multipliers_by_tag(
        task_repo.estimate_actual_pairs_for_user(conn, user_id)
    )
    history = task_repo.estimate_history_for_user(conn, user_id)
    return {
        "overload": build_overload(pending),
        "report_card": build_report_card(history, multipliers),
    }
