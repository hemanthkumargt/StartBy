"""The spoken briefing: what matters today, in a sharp, dry executive-assistant
voice. Everything it says comes from data the app already computes (start-by,
risk, replan, overload) — no AI call, so it works when Gemini is down or
over quota, and it can never invent a task.

build_briefing() returns the script (what is read aloud) plus the same
priorities as structured items (what is shown on screen: always visible, so
nobody depends on audio)."""

import hashlib
import sqlite3
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app import timeutil
from app.constants import STALE_OVERDUE_DAYS
from app.services import estimate_service, insights_service, task_service
from app.services.insights_service import plural

MAX_PRIORITIES = 3

_CLOSERS = (
    "That's the picture. Go make it look easy.",
    "That's everything. I'll be here when you're done.",
    "That's the list. You've handled worse.",
    "That's it. Go. I'll keep the clock.",
)
_ALL_CLEAR = (
    "Your slate is clear. Enjoy it, and I won't tell anyone.",
    "Nothing is pending. Suspicious, but I'll take it.",
)


def _greeting(hour: int, first_name: str, assistant_name: str) -> str:
    """The assistant introduces itself by name, so the name a user chose in
    Settings is the one they actually hear."""
    part = "Good morning" if hour < 12 else "Good afternoon" if hour < 17 else "Good evening"
    return f"{part}, {first_name}. {spoken(assistant_name)} here."


def _pick(options: tuple[str, ...], seed: str) -> str:
    """Stable for a given user and day (it should not reshuffle on every click),
    but different from day to day."""
    return options[int(hashlib.sha256(seed.encode()).hexdigest(), 16) % len(options)]


def say_time(iso: str, tz_name: str, now_local: datetime) -> str:
    local = timeutil.utc_iso_to_local(iso, tz_name)
    clock = local.strftime("%I:%M %p").lstrip("0")
    days = (local.date() - now_local.date()).days
    if days == 0:
        return f"today at {clock}"
    if days == 1:
        return f"tomorrow at {clock}"
    if 1 < days < 7:
        return f"{local.strftime('%A')} at {clock}"
    return f"{local.strftime('%d %B').lstrip('0')} at {clock}"


def spoken(text: str) -> str:
    """A title/name as it can safely precede our own full stop: "Call mom!" must
    not become "Call mom!." (read as a stray pause, and split into a ".." chunk)."""
    return text.strip().rstrip(".!?…").strip() or text.strip()


def _classify(task: dict[str, Any], today_local: Any, tz_name: str) -> str | None:
    """Which kind of attention a pending task needs right now, or None."""
    risk = task.get("risk")
    if risk == "red":
        return "start_now_overdue" if task.get("is_overdue") else "start_now"
    if risk == "amber":
        return "start_soon"
    due = task.get("due_at")
    if due is None:
        return None
    if task.get("is_overdue"):
        return "overdue"
    if timeutil.utc_iso_to_local(due, tz_name).date() == today_local:
        return "due_today"
    return None


_RANK = {"start_now": 0, "start_now_overdue": 1, "start_soon": 2, "overdue": 3, "due_today": 4}


def _line(
    kind: str, task: dict[str, Any], tz_name: str, now_local: datetime, *, repeat: bool = False
) -> str:
    """`repeat` is True for the 2nd+ item of the same kind: it gets a short line,
    because hearing the identical sentence three times in a row is grating."""
    title = spoken(task["title"])
    if repeat and kind == "start_now":
        return f"{title}. Same deal, start it now."
    if repeat and kind == "start_now_overdue":
        return f"{title}. Also overdue and past its start."
    if kind == "start_now":
        line = f"{title}. You should have started already. Start it now."
        replan = task.get("replan")
        if replan and replan.get("late_by_hours", 0) > 0:
            late = estimate_service.format_hours(replan["late_by_hours"])
            line += f" At your pace it lands about {late} after the deadline, so ask for more time."
        return line
    if kind == "start_now_overdue":
        return f"{title}. It's overdue and past its start time. Start now, or move the deadline."
    if kind == "start_soon":
        return f"{title}. Start by {say_time(task['start_by'], tz_name, now_local)}."
    if kind == "overdue":
        return f"{title} is overdue."
    return f"{title} is due {say_time(task['due_at'], tz_name, now_local)}."


def build_briefing(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    user_name: str,
    tz_name: str,
    flags: dict,
    assistant_name: str = "SARA",
    pending: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """`pending` lets a caller that already loaded the user's pending tasks (the
    assistant does) pass them in instead of paying for a second query + serialise."""
    if pending is None:
        pending = task_service.list_tasks(conn, user_id=user_id, status="pending", flags=flags)
    now_local = timeutil.utcnow().astimezone(ZoneInfo(tz_name))
    today = now_local.date()
    first_name = spoken((user_name.split() or ["there"])[0])
    seed = f"{user_id}:{today.isoformat()}"

    live = [t for t in pending if not insights_service.is_abandoned(t)]
    abandoned = len(pending) - len(live)

    graded = []
    for task in live:
        kind = _classify(task, today, tz_name)
        if kind:
            # not-yet-overdue before overdue inside a kind, then by urgency
            graded.append(
                (
                    _RANK[kind],
                    bool(task.get("is_overdue")),
                    task.get("start_by") or task["due_at"],
                    kind,
                    task,
                )
            )
    graded.sort(key=lambda g: g[:3])

    top = graded[:MAX_PRIORITIES]
    items = []
    seen_kinds: set[str] = set()
    for *_ignored, kind, t in top:
        items.append(
            {
                "id": t["id"],
                "title": t["title"],
                "kind": kind,
                "line": _line(kind, t, tz_name, now_local, repeat=kind in seen_kinds),
            }
        )
        seen_kinds.add(kind)

    parts = [_greeting(now_local.hour, first_name, assistant_name)]
    if not live and not abandoned:
        parts.append(_pick(_ALL_CLEAR, seed))
    elif not items and not live:
        parts.append("Nothing current is waiting on you.")  # only abandoned tasks remain
    elif not items:
        parts.append(
            f"Nothing needs you right now. {plural(len(live), 'task')} on the list, none urgent."
        )
    else:
        opener = (
            "One thing needs you."
            if len(items) == 1
            else f"{plural(len(items), 'thing')} need you."
        )
        parts.append(opener)
        for number, item in enumerate(items, start=1):
            parts.append(f"{number}. {item['line']}" if len(items) > 1 else item["line"])
        extra = len(graded) - len(items)
        if extra > 0:
            parts.append(
                f"{plural(extra, 'more item')} {'is' if extra == 1 else 'are'} on the watch list."
            )

    if flags.get("estimates"):
        overload = insights_service.build_overload(pending)
        if overload["level"] != "none":
            parts.append(
                "Honestly, that's more than one person should carry. "
                "Move a deadline or drop something."
            )
    if abandoned:
        verb = "has" if abandoned == 1 else "have"
        parts.append(
            f"Also, {plural(abandoned, 'task')} {verb} been overdue "
            f"for over {STALE_OVERDUE_DAYS} days. Do it, or delete it."
        )
    if items or abandoned:
        parts.append(_pick(_CLOSERS, seed))

    return {
        "assistant": assistant_name,
        "script": " ".join(parts),
        "items": items,
        "pending": len(pending),
    }
