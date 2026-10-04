"""Voice questions: "what should I do now?", "what's due tomorrow?", "how many
are overdue?" — answered from the user's own data with fixed rules, no AI.

Read-only by construction: nothing here writes anything, and a request to ADD a
task is handed back to the client as an action that opens Smart Capture, where
the usual preview-and-confirm applies (I14). Because there is no model in the
loop, the assistant cannot be talked into doing anything (no prompt injection)
and works with no network or quota."""

import re
import sqlite3
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app import timeutil
from app.services import briefing_service, insights_service, task_service
from app.services.insights_service import plural

MAX_QUESTION_CHARS = 300
_LIST_LIMIT = 5

_HELP = (
    "I can tell you what to do now, what's due today or tomorrow, how many tasks are pending "
    "or overdue, how heavy your workload is, how accurate your estimates are, or explain a "
    "start time. Say add, then a task, and I'll open capture for you."
)


def _rx(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.I)


# Order matters: the first match wins (an "add ..." request must not be read as a question).
_INTENTS: list[tuple[str, re.Pattern[str]]] = [
    ("add", _rx(r"^\s*(?:please\s+)?(?:add|create|new task|remind me|i need to|note)\b")),
    ("explain", _rx(
        r"\b(?:why|explain|how (?:is|was|did|do you) (?:that|this|the)?\s*(?:calculated|work)"
        r"|how.*(?:start time|start by|calculated))"
    )),
    ("accuracy", _rx(
        r"\b(?:accura|how good|how well).*(?:estimat|guess)|"
        r"estimat\w*.*(?:accura|good|bad|right|wrong|off)"
    )),
    ("workload", _rx(r"\b(?:overload|overwhelm|too much|workload|swamped|behind|busy)\w*")),
    ("count", _rx(r"\bhow many\b")),
    ("due", _rx(r"\b(?:due|deadline|coming up|on my plate|have on|scheduled)\b")),
    ("now", _rx(
        r"\b(?:what|which)\b.*\b(?:do|should|work on|start|tackle)\b.*\b(?:now|next|first|today)\b"
        r"|\b(?:priority|priorities|urgent|most important)\b|\bwhere (?:do|should) i start\b"
        r"|\bwhat now\b"
    )),
    ("brief", _rx(
        r"\b(?:brief|briefing|summary|summari[sz]e|catch me up|what.?s going on"
        r"|good (?:morning|afternoon|evening))\b"
    )),
    ("help", _rx(r"\b(?:help|what can you do|what do you do)\b")),
]  # fmt: skip


def classify(text: str) -> str:
    for name, pattern in _INTENTS:
        if pattern.search(text):
            return name
    return "unknown"


def _period(text: str) -> str:
    lowered = text.lower()
    if "tomorrow" in lowered:
        return "tomorrow"
    if "week" in lowered:
        return "week"
    return "today"


def _titles(tasks: list[dict[str, Any]], tz_name: str, now_local: datetime) -> str:
    parts = []
    for t in tasks[:_LIST_LIMIT]:
        when = briefing_service.say_time(t["due_at"], tz_name, now_local)
        parts.append(f"{briefing_service.spoken(t['title'])}, {when}")
    more = len(tasks) - _LIST_LIMIT
    return "; ".join(parts) + (f"; and {more} more" if more > 0 else "") + "."


def strip_wake_name(text: str, assistant_name: str) -> str:
    """ "Jarvis, what's due today" -> "what's due today". Only a leading name (with an
    optional hey/hi/ok) followed by a comma, colon or space; a name appearing later in
    the sentence is left alone."""
    pattern = re.compile(
        rf"^\s*(?:(?:hey|hi|hello|ok|okay)[\s,]+)?{re.escape(assistant_name.strip())}\b\s*[,:]?\s*",
        re.I,
    )
    return pattern.sub("", text, count=1)


def answer(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    user_name: str,
    tz_name: str,
    flags: dict,
    text: object,
    assistant_name: str = "SARA",
) -> dict[str, Any]:
    if not isinstance(text, str) or not text.strip():
        return {"intent": "empty", "answer": "I didn't catch a question. " + _HELP, "action": None}
    question = " ".join(text.split())[:MAX_QUESTION_CHARS]
    question = strip_wake_name(question, assistant_name).strip()
    if not question:  # they only said the assistant's name
        return {"intent": "empty", "answer": "Yes? " + _HELP, "action": None}
    intent = classify(question)

    if intent == "add":
        return {
            "intent": "add",
            "answer": "Opening capture. Check the draft, then confirm to save it.",
            "action": {"type": "capture", "text": question},
        }
    if intent == "help":
        return {"intent": "help", "answer": _HELP, "action": None}

    pending = task_service.list_tasks(conn, user_id=user_id, status="pending", flags=flags)
    now_local = timeutil.utcnow().astimezone(ZoneInfo(tz_name))
    briefing = briefing_service.build_briefing(
        conn, user_id=user_id, user_name=user_name, tz_name=tz_name, flags=flags,
        assistant_name=assistant_name, pending=pending,
    )  # fmt: skip

    if intent == "brief":
        reply = briefing["script"]
    elif intent == "now":
        top = briefing["items"][0] if briefing["items"] else None
        reply = (
            f"Start with {top['line']}" if top else "Nothing is urgent right now. Enjoy the quiet."
        )
    elif intent == "due":
        period = _period(question)
        today = now_local.date()
        end = today + timedelta(days=0 if period == "today" else 1 if period == "tomorrow" else 6)
        start = today + timedelta(days=1) if period == "tomorrow" else today
        hits = sorted(
            (
                t for t in pending
                if t.get("due_at")
                and start <= timeutil.utc_iso_to_local(t["due_at"], tz_name).date() <= end
            ),
            key=lambda t: t["due_at"],
        )  # fmt: skip
        label = {"today": "today", "tomorrow": "tomorrow", "week": "in the next seven days"}[period]
        reply = (
            f"Nothing is due {label}."
            if not hits
            else f"{plural(len(hits), 'task')} due {label}: {_titles(hits, tz_name, now_local)}"
        )
    elif intent == "count":
        lowered = question.lower()
        overdue = sum(1 for t in pending if t.get("is_overdue"))
        if "overdue" in lowered or "late" in lowered:
            reply = f"{plural(overdue, 'task')} {'is' if overdue == 1 else 'are'} overdue."
        elif "done" in lowered or "complet" in lowered or "finish" in lowered:
            done = len(task_service.list_tasks(conn, user_id=user_id, status="done", flags=flags))
            reply = f"You've completed {plural(done, 'task')}."
        else:
            reply = f"{plural(len(pending), 'task')} pending, {overdue} of them overdue."
    elif intent == "workload":
        if not flags.get("estimates"):
            reply = (
                f"You have {plural(len(pending), 'pending task')}. Turn on effort estimates and "
                "I can tell you how heavy the load really is."
            )
        else:
            overload = insights_service.build_overload(pending)
            reply = (
                overload["message"]
                if overload["level"] != "none"
                else "Your workload looks manageable. Nothing is stacking up."
            )
    elif intent == "accuracy":
        if not flags.get("estimates"):
            reply = (
                "Turn on effort estimates and log your actual hours, and I can score your guesses."
            )
        else:
            insights = insights_service.get_insights(conn, user_id=user_id, flags=flags)
            reply = insights["report_card"]["summary"]
    elif intent == "explain":
        explained = next((t for t in pending if t.get("start_by_explanation")), None)
        top_id = briefing["items"][0]["id"] if briefing["items"] else None
        target = next(
            (t for t in pending if t["id"] == top_id and t.get("start_by_explanation")), explained
        )
        reply = (
            f"For {briefing_service.spoken(target['title'])}: {target['start_by_explanation']}"
            if target
            else "Start-by is the due time minus your estimate, stretched by your usual pace and "
            "a fifteen percent buffer. Add an estimate to a task and I'll show the working."
        )
    else:
        reply = "Sorry, I didn't follow that. " + _HELP
        intent = "unknown"
    return {"intent": intent, "answer": reply, "action": None}
