"""Finds tasks due for a reminder and sends them, respecting PRD invariants
I7 (each kind sent at most once per task) and the safety rule that cron
processes at most MAX_PER_RUN tasks and never marks a failed send as sent."""

import logging
import sqlite3
from collections.abc import Callable, Iterable

from app import timeutil
from app.constants import DEFAULT_MULTIPLIER
from app.repositories import reminder_repo, task_repo
from app.services import estimate_service
from app.services.notifier import Notifier

logger = logging.getLogger(__name__)

MAX_PER_RUN = 100
DUE_SOON_WINDOW_HOURS = 24


def _send_candidates(
    conn: sqlite3.Connection,
    notifier: Notifier,
    candidates: Iterable[sqlite3.Row],
    *,
    kind: str,
    subject: Callable[[sqlite3.Row], str],
    body: Callable[[sqlite3.Row], str],
    budget: int,
) -> tuple[int, int]:
    """Shared by all three reminder kinds: send, record on success only (a
    failed send must retry next run, never counted as sent), stop once the
    shared cron-run budget is spent. Returns (sent_count, remaining_budget)."""
    sent_count = 0
    for row in candidates:
        if budget <= 0:
            break
        if notifier.send(to=row["email"], subject=subject(row), body=body(row)):
            reminder_repo.record_sent(conn, row["task_id"], kind)
            sent_count += 1
            budget -= 1
    return sent_count, budget


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

    window_end_iso = timeutil.add_hours_iso(now_iso, DUE_SOON_WINDOW_HOURS)
    due_soon_sent, budget = _send_candidates(
        conn,
        notifier,
        reminder_repo.find_due_soon_candidates(
            conn, now_iso=now_iso, window_end_iso=window_end_iso, limit=budget
        ),
        kind="due_soon",
        subject=lambda row: f'Reminder: "{row["title"]}" is due within 24 hours',
        body=lambda row: (
            f'Hi {row["user_name"]}, your task "{row["title"]}" is due within 24 hours.'
        ),
        budget=budget,
    )

    overdue_sent, budget = _send_candidates(
        conn,
        notifier,
        reminder_repo.find_overdue_candidates(conn, now_iso=now_iso, limit=budget),
        kind="overdue",
        subject=lambda row: f'Overdue: "{row["title"]}"',
        body=lambda row: f'Hi {row["user_name"]}, your task "{row["title"]}" is now overdue.',
        budget=budget,
    )

    result = {"due_soon_sent": due_soon_sent, "overdue_sent": overdue_sent}

    # I15: with the flag off, start_by doesn't conceptually exist, so this
    # whole reminder kind — including the key in the response — is a no-op,
    # not just zero. Also skipped once budget is already spent: candidates
    # can't be pre-filtered to "actually red" in SQL (start_by isn't a
    # stored column), so there's no point paying for the fetch at all if
    # nothing could be sent from it anyway.
    if flags.get("estimates", False) and budget > 0:
        # I13: the same per-user-per-tag multiplier task_service uses for
        # the dashboard/API, not the cold-start default — otherwise a tag
        # with learned history could show red on the dashboard while this
        # cron, still on 1.5x, disagrees about whether it's actually red
        # yet (or the reverse). Cached per user since one cron run spans
        # every user's candidates, unlike task_service's one-user-per-request.
        multipliers_by_user: dict[int, dict[str, float]] = {}

        def multiplier_for(row: sqlite3.Row) -> float:
            user_id = row["user_id"]
            if user_id not in multipliers_by_user:
                multipliers_by_user[user_id] = estimate_service.multipliers_by_tag(
                    task_repo.estimate_actual_pairs_for_user(conn, user_id)
                )
            return multipliers_by_user[user_id].get(row["tag"], DEFAULT_MULTIPLIER)

        # A task further out than the longest possible lead time can never
        # be red yet however its own estimate/multiplier work out, so the
        # repo can prune it in SQL via the existing due_at index instead of
        # this service layer fetching and discarding it every run.
        horizon_iso = timeutil.add_hours_iso(now_iso, estimate_service.MAX_LEAD_TIME_HOURS)
        red_by_start_by = []
        for row in reminder_repo.find_start_now_candidates(conn, due_before_iso=horizon_iso):
            start_by = estimate_service.compute_start_by(
                row["due_at"], row["estimate_hours"], multiplier_for(row)
            )
            if estimate_service.compute_risk(row["status"], start_by) == "red":
                red_by_start_by.append((start_by, row))
        # SQL ordered by due_at (its only candidate-pruning column), but the
        # budget should go to the most overdue-by-start_by task first —
        # that's what "red" actually measures, and what pick_do_this_now
        # already prioritizes by for the same reason.
        red_candidates = [row for _, row in sorted(red_by_start_by, key=lambda pair: pair[0])]

        start_now_sent, budget = _send_candidates(
            conn,
            notifier,
            red_candidates,
            kind="start_now",
            subject=lambda row: f'Time to start: "{row["title"]}"',
            body=lambda row: (
                f'Hi {row["user_name"]}, it\'s time to start "{row["title"]}" '
                "to finish it by your due date."
            ),
            budget=budget,
        )
        result["start_now_sent"] = start_now_sent

    logger.info(
        "cron_reminders due_soon_sent=%s overdue_sent=%s start_now_sent=%s",
        due_soon_sent,
        overdue_sent,
        start_now_sent,
    )
    return result
