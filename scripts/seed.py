#!/usr/bin/env python3
"""Seed a demo account with realistic tasks, for local dev and presentations.

Usage:
    python scripts/seed.py            # create the demo user if missing
    python scripts/seed.py --reset    # wipe and recreate the demo account

Credentials come from SEED_USER_EMAIL / SEED_USER_PASSWORD in .env.
"""

import argparse
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from app import create_app, timeutil  # noqa: E402
from app.config import Config  # noqa: E402
from app.db import get_db  # noqa: E402
from app.repositories import user_repo  # noqa: E402
from app.services import auth_service, task_service  # noqa: E402

# (title, tag, days_from_now or None, already_done)
# Mix: ~5 overdue, ~4 due today, ~6 due this week, ~5 due later,
#      ~4 no due date, ~6 already done — 30 total, spread across all 3 tags.
SAMPLE_TASKS = [
    ("Submit DBMS assignment 3", "study", -3, False),
    ("Pay hostel mess fee", "personal", -2, False),
    ("Return library books", "personal", -1, False),
    ("Reply to placement cell email", "work", -1, False),
    ("Lab record submission — OS course", "study", -1, False),
    ("Team standup notes", "work", 0, False),
    ("Buy groceries for the week", "personal", 0, False),
    ("Revise OS notes before class", "study", 0, False),
    ("Call home", "personal", 0, False),
    ("Group project meeting prep", "work", 1, False),
    ("Finish LeetCode daily problem", "study", 1, False),
    ("Gym session", "personal", 2, False),
    ("Review PR from teammate", "work", 2, False),
    ("Study for DBMS midterm", "study", 3, False),
    ("Clean room before inspection", "personal", 4, False),
    ("Attend placement seminar", "work", 5, False),
    ("Draft weekly status report", "work", 10, False),
    ("Plan weekend trip", "personal", 12, False),
    ("Read research paper for seminar", "study", 14, False),
    ("Renew gym membership", "personal", 20, False),
    ("Organise class notes", "study", None, False),
    ("Fix laptop keyboard", "personal", None, False),
    ("Update resume", "work", None, False),
    ("Explore internship postings", "work", None, False),
    ("Submit hackathon registration", "work", -5, True),
    ("Finish Python assignment", "study", -4, True),
    ("Wash clothes", "personal", -3, True),
    ("Attend orientation session", "work", -6, True),
    ("Complete DSA practice set 2", "study", -2, True),
    ("Book exam hall ticket", "personal", -7, True),
]


def build_due_at(days_offset: int | None, tz_name: str) -> str | None:
    """6 PM, in the demo user's own timezone — not a raw UTC hour, so the
    data reads naturally for whoever is looking at it (PRD invariant I9)."""
    if days_offset is None:
        return None
    local_now = timeutil.utc_iso_to_local(timeutil.utcnow_iso(), tz_name)
    local_due = (local_now + timedelta(days=days_offset)).replace(
        hour=18, minute=0, second=0, microsecond=0, tzinfo=None
    )
    return timeutil.local_to_utc_iso(local_due, tz_name)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="wipe and recreate the demo account")
    args = parser.parse_args()

    app = create_app(Config())
    with app.app_context():
        conn = get_db()
        email = app.config["SEED_USER_EMAIL"]
        password = app.config["SEED_USER_PASSWORD"]

        existing = user_repo.find_by_email(conn, email)
        if existing is not None:
            if not args.reset:
                print(f"Demo user {email} already exists. Use --reset to recreate it.")
                return
            user_repo.delete_by_email(conn, email)
            print(f"Removed existing demo user {email} (--reset).")

        user = auth_service.register(
            conn,
            name="Demo Student",
            email=email,
            password=password,
            timezone=app.config["DEFAULT_TIMEZONE"],
        )
        print(f"Created demo user {email}")

        tz_name = app.config["DEFAULT_TIMEZONE"]
        for title, tag, days_offset, done in SAMPLE_TASKS:
            task = task_service.create_task(
                conn,
                user_id=user.id,
                title=title,
                tag=tag,
                due_at=build_due_at(days_offset, tz_name),
            )
            if done:
                task_service.complete_task(conn, user_id=user.id, task_id=task["id"])

        print(f"Seeded {len(SAMPLE_TASKS)} tasks across work/study/personal.")


if __name__ == "__main__":
    main()
