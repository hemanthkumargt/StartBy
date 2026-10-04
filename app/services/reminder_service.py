"""Finds tasks due for a reminder and sends them, respecting PRD invariants
I7 (each kind sent at most once per task) and the safety rule that cron
processes at most MAX_PER_RUN tasks and never marks a failed send as sent."""

import logging
import sqlite3
import time
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from app import timeutil
from app.constants import DEFAULT_MULTIPLIER, START_BY_BUFFER
from app.repositories import reminder_repo, task_repo
from app.services import estimate_service
from app.services.notifier import Notifier

logger = logging.getLogger(__name__)

MAX_PER_RUN = 100
# Candidates are fetched past the send budget so one user's un-sendable rows
# (a rejected address, a bounced mailbox) can't fill the query window and hide
# everyone else's reminders; _interleave_by_user then serves users fairly.
FETCH_LIMIT = 1000
# SMTP down means every attempt costs ~22s: give up on this run after a few
# failures in a row instead of holding a web worker for half an hour.
MAX_CONSECUTIVE_FAILURES = 5
# One undeliverable address (a typo'd or bounced mailbox) must not slow every sweep
# by a failed ~22 s SMTP attempt per task: after this many failures in a row for the
# same user, the rest of that user's reminders are skipped for the run.
MAX_USER_FAILURES = 3
# One cron request must finish well inside gunicorn's worker timeout (120s in
# deploy/startby.service): a run killed mid-send would leave a claimed-but-never-
# sent reminder behind. Stop starting new sends after this long; the rest go next run.
RUN_SECONDS = 20
DUE_SOON_WINDOW_HOURS = 24


class _Run:
    """State shared by all three reminder kinds in one cron run: a failure
    streak that does NOT reset between kinds (with SMTP down, 5 failures end the
    whole run, not 5 per kind) and a wall-clock deadline."""

    def __init__(self) -> None:
        self.failures = 0
        self.user_failures: dict[Any, int] = {}
        self.skipped_users: set[Any] = set()
        self.deadline = time.monotonic() + RUN_SECONDS
        self.stopped = False

    def should_stop(self) -> bool:
        if not self.stopped and time.monotonic() >= self.deadline:
            logger.warning("reminders_stopped_at_run_deadline")
            self.stopped = True
        return self.stopped


def _when(row: Mapping[str, Any], key: str = "due_at") -> str:
    """A due time in the USER's own timezone (a date alone in a reminder email
    forces the reader to open the app to learn when)."""
    try:
        local = timeutil.utc_iso_to_local(row[key], row["user_timezone"])
    except (KeyError, ValueError, TypeError):
        return "its due time"
    return local.strftime("%a %d %b, %H:%M")


def _one_line(text: object) -> str:
    return " ".join(str(text).split())


def _interleave_by_user(candidates: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Round-robin across users (keeping each user's own order), so under the
    per-run budget no single user's backlog can starve the rest."""
    queues: dict[Any, list[Mapping[str, Any]]] = {}
    for row in candidates:
        queues.setdefault(row["user_id"], []).append(row)
    ordered: list[Mapping[str, Any]] = []
    while queues:
        for key in list(queues):
            ordered.append(queues[key].pop(0))
            if not queues[key]:
                del queues[key]
    return ordered


def _send_candidates(
    conn: sqlite3.Connection,
    notifier: Notifier,
    candidates: Iterable[Mapping[str, Any]],
    *,
    kind: str,
    subject: Callable[[Mapping[str, Any]], str],
    body: Callable[[Mapping[str, Any]], str],
    budget: int,
    run: "_Run | None" = None,
) -> tuple[int, int]:
    """Shared by all three reminder kinds: send, record on success only (a
    failed send must retry next run, never counted as sent), stop once the
    shared cron-run budget is spent. Returns (sent_count, remaining_budget)."""
    sent_count = 0
    run = run or _Run()
    for row in _interleave_by_user(candidates):
        if budget <= 0 or run.should_stop():
            break
        if row["user_id"] in run.skipped_users:
            continue  # their address keeps failing: nothing sent, nothing claimed
        if not reminder_repo.claim(conn, row["task_id"], kind):
            continue  # another worker/trigger already took this one
        # A failed attempt spends budget too: that bounds how long one run can take.
        budget -= 1
        if notifier.send(to=row["email"], subject=_one_line(subject(row)), body=body(row)):
            sent_count += 1
            run.failures = 0
            run.user_failures.pop(row["user_id"], None)
        else:
            reminder_repo.release(conn, row["task_id"], kind)  # retry next run
            run.failures += 1
            user_failures = run.user_failures.get(row["user_id"], 0) + 1
            run.user_failures[row["user_id"]] = user_failures
            if user_failures >= MAX_USER_FAILURES:
                run.skipped_users.add(row["user_id"])
                logger.warning(
                    "reminders_user_skipped user_id=%s failures=%s", row["user_id"], user_failures
                )
            if run.failures >= MAX_CONSECUTIVE_FAILURES:
                logger.error("reminders_aborted_after_failures kind=%s", kind)
                run.stopped = True
                break
    return sent_count, budget


def _find_start_now_candidates(conn: sqlite3.Connection, now_iso: str) -> list[Mapping[str, Any]]:
    """Pending tasks that are actually red right now, ordered by start_by
    (most overdue first — that's what "red" measures, and what
    pick_do_this_now already prioritizes by for the same reason). Each
    candidate is a plain dict (the repo row plus an `explanation` key),
    since sqlite3.Row is read-only and the reminder email needs to say how
    the start time was worked out."""
    # I13: the same per-user-per-tag multiplier task_service uses for the
    # dashboard/API, not the cold-start default — otherwise a tag with
    # learned history could show red on the dashboard while this cron,
    # still on 1.5x, disagrees about whether it's actually red yet (or the
    # reverse). Cached per user since one cron run spans every user's
    # candidates, unlike task_service's one-user-per-request.
    multipliers_by_user: dict[int, dict[str, float]] = {}

    def multiplier_for(row: sqlite3.Row) -> tuple[float, bool]:
        return _multiplier_for_user_tag(conn, row, multipliers_by_user)

    # A task further out than the longest possible lead time can never be
    # red yet however its own estimate/multiplier work out, so the repo can
    # prune it in SQL via the existing due_at index instead of this service
    # layer fetching and discarding it every run.
    horizon_iso = timeutil.add_hours_iso(now_iso, estimate_service.MAX_LEAD_TIME_HOURS)
    red_by_start_by: list[tuple[str, Mapping[str, Any]]] = []
    for row in reminder_repo.find_start_now_candidates(conn, due_before_iso=horizon_iso):
        if timeutil.is_before_now(row["due_at"]):
            continue  # already overdue: the overdue notice is the message now
        multiplier, learned = multiplier_for(row)
        red = _as_red_candidate(row, multiplier, learned)
        if red is not None:
            red_by_start_by.append(red)
    return [candidate for _, candidate in sorted(red_by_start_by, key=lambda pair: pair[0])]


def _multiplier_for_user_tag(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    cache: dict[int, dict[str, float]],
) -> tuple[float, bool]:
    """(multiplier, learned) — learned is False for the cold-start default.
    `cache` holds each user's per-tag multipliers so one cron run, which
    spans every user's candidates, queries each user's history only once."""
    user_id = row["user_id"]
    if user_id not in cache:
        cache[user_id] = estimate_service.multipliers_by_tag(
            task_repo.estimate_actual_pairs_for_user(conn, user_id)
        )
    by_tag = cache[user_id]
    return by_tag.get(row["tag"], DEFAULT_MULTIPLIER), row["tag"] in by_tag


def _as_red_candidate(
    row: sqlite3.Row, multiplier: float, learned: bool
) -> tuple[str, Mapping[str, Any]] | None:
    """(start_by, candidate dict) if this task is red right now, else None."""
    start_by = estimate_service.compute_start_by(row["due_at"], row["estimate_hours"], multiplier)
    if estimate_service.compute_risk(row["status"], start_by) != "red":
        return None
    explanation = estimate_service.explain_start_by(
        row["estimate_hours"], multiplier, tag=row["tag"], learned=learned
    )
    lead_hours = row["estimate_hours"] * multiplier * (1 + START_BY_BUFFER)
    replan = estimate_service.describe_replan(
        estimate_service.compute_replan(row["due_at"], start_by), lead_hours
    )
    return start_by, {**dict(row), "explanation": explanation, "replan": replan}


def _start_now_subject(row: Mapping[str, Any]) -> str:
    return f'Time to start: "{_one_line(row["title"])}"'


def _start_now_body(row: Mapping[str, Any]) -> str:
    return (
        f'Hi {row["user_name"]}, it\'s time to start "{row["title"]}" '
        f"to finish it by {_when(row)}.\n\n"
        f'How we worked this out: {row["explanation"]}\n\n'
        f'Updated plan: {row["replan"]}'
    )


def send_start_now_for_task(
    conn: sqlite3.Connection, notifier: Notifier, task_id: int
) -> dict[str, Any]:
    """Exact-time path (Cloud Tasks): decide for ONE task whether its
    start-now reminder is due right now, using the same rules and the same
    once-per-task record (I7) as the cron sweep. Stale triggers are safe:
    a task whose start_by moved later, or that was completed/deleted since
    the trigger was queued, simply isn't eligible and nothing is sent."""
    row = reminder_repo.find_start_now_candidate_for_task(conn, task_id)
    if row is None:
        return {"sent": False, "reason": "not_eligible"}
    if timeutil.is_before_now(row["due_at"]):
        return {"sent": False, "reason": "already_overdue"}
    multiplier, learned = _multiplier_for_user_tag(conn, row, {})
    red = _as_red_candidate(row, multiplier, learned)
    if red is None:
        return {
            "sent": False,
            "reason": "not_yet_red",
            "start_by": estimate_service.compute_start_by(
                row["due_at"], row["estimate_hours"], multiplier
            ),
        }
    candidate = red[1]
    if not reminder_repo.claim(conn, task_id, "start_now"):
        return {"sent": False, "reason": "not_eligible"}  # lost a race: already sent
    sent = notifier.send(
        to=candidate["email"],
        subject=_start_now_subject(candidate),
        body=_start_now_body(candidate),
    )
    if not sent:
        reminder_repo.release(conn, task_id, "start_now")
        return {"sent": False, "reason": "send_failed"}
    return {"sent": True, "reason": "sent"}


def run_reminders(
    conn: sqlite3.Connection,
    notifier: Notifier,
    *,
    now_iso: str,
    max_per_run: int = MAX_PER_RUN,
    flags: dict | None = None,
) -> dict[str, int]:
    flags = flags or {}
    budget = max_per_run
    start_now_sent = 0
    run = _Run()

    window_end_iso = timeutil.add_hours_iso(now_iso, DUE_SOON_WINDOW_HOURS)
    due_soon_sent, budget = _send_candidates(
        conn,
        notifier,
        reminder_repo.find_due_soon_candidates(
            conn, now_iso=now_iso, window_end_iso=window_end_iso, limit=FETCH_LIMIT
        ),
        kind="due_soon",
        subject=lambda row: f'Reminder: "{_one_line(row["title"])}" is due within 24 hours',
        body=lambda row: (
            f'Hi {row["user_name"]}, your task "{row["title"]}" is due within 24 hours '
            f"(by {_when(row)})."
        ),
        budget=budget,
        run=run,
    )

    overdue_sent, budget = _send_candidates(
        conn,
        notifier,
        reminder_repo.find_overdue_candidates(conn, now_iso=now_iso, limit=FETCH_LIMIT),
        kind="overdue",
        subject=lambda row: f'Overdue: "{_one_line(row["title"])}"',
        body=lambda row: (
            f'Hi {row["user_name"]}, your task "{row["title"]}" is now overdue '
            f"(it was due {_when(row)})."
        ),
        budget=budget,
        run=run,
    )

    result = {"due_soon_sent": due_soon_sent, "overdue_sent": overdue_sent}

    # I15: with the flag off, start_by doesn't conceptually exist, so this
    # whole reminder kind — including the key in the response — is a no-op,
    # not just zero. The key's presence depends only on the flag: whether
    # budget happened to run out first must not change the response shape,
    # only the count (0) it reports.
    if flags.get("estimates", False):
        # Skipped once budget is already spent: candidates can't be
        # pre-filtered to "actually red" in SQL (start_by isn't a stored
        # column), so there's no point paying for the fetch at all if
        # nothing could be sent from it anyway.
        candidates = _find_start_now_candidates(conn, now_iso) if budget > 0 else []
        start_now_sent, budget = _send_candidates(
            conn,
            notifier,
            candidates,
            kind="start_now",
            subject=_start_now_subject,
            body=_start_now_body,
            budget=budget,
            run=run,
        )
        result["start_now_sent"] = start_now_sent

    logger.info(
        "cron_reminders due_soon_sent=%s overdue_sent=%s start_now_sent=%s",
        due_soon_sent,
        overdue_sent,
        start_now_sent,
    )
    return result
