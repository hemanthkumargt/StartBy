"""Finds tasks due for a reminder and sends them, respecting PRD invariants
I7 (each kind sent at most once per task) and the safety rule that cron
processes at most MAX_PER_RUN tasks and never marks a failed send as sent."""

import logging
import sqlite3

from app import timeutil
from app.repositories import reminder_repo
from app.services.notifier import Notifier

logger = logging.getLogger(__name__)

MAX_PER_RUN = 100
DUE_SOON_WINDOW_HOURS = 24


def run_reminders(
    conn: sqlite3.Connection, notifier: Notifier, *, now_iso: str, max_per_run: int = MAX_PER_RUN
) -> dict[str, int]:
    budget = max_per_run
    due_soon_sent = 0
    overdue_sent = 0

    window_end_iso = timeutil.add_hours_iso(now_iso, DUE_SOON_WINDOW_HOURS)
    for row in reminder_repo.find_due_soon_candidates(
        conn, now_iso=now_iso, window_end_iso=window_end_iso, limit=budget
    ):
        if budget <= 0:
            break
        sent = notifier.send(
            to=row["email"],
            subject=f'Reminder: "{row["title"]}" is due within 24 hours',
            body=f'Hi {row["user_name"]}, your task "{row["title"]}" is due within 24 hours.',
        )
        if sent:
            reminder_repo.record_sent(conn, row["task_id"], "due_soon")
            due_soon_sent += 1
            budget -= 1

    for row in reminder_repo.find_overdue_candidates(conn, now_iso=now_iso, limit=budget):
        if budget <= 0:
            break
        sent = notifier.send(
            to=row["email"],
            subject=f'Overdue: "{row["title"]}"',
            body=f'Hi {row["user_name"]}, your task "{row["title"]}" is now overdue.',
        )
        if sent:
            reminder_repo.record_sent(conn, row["task_id"], "overdue")
            overdue_sent += 1
            budget -= 1

    logger.info("cron_reminders due_soon_sent=%s overdue_sent=%s", due_soon_sent, overdue_sent)
    return {"due_soon_sent": due_soon_sent, "overdue_sent": overdue_sent}
