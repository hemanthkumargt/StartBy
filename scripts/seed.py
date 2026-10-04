#!/usr/bin/env python3
"""Seed a demo account with realistic tasks, for local dev and presentations.

Usage:
    python scripts/seed.py            # create the demo user if missing
    python scripts/seed.py --reset    # wipe and recreate the demo account

Credentials come from SEED_USER_EMAIL / SEED_USER_PASSWORD in .env.
"""

import argparse
import os
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from app.gcp import secrets as gcp_secrets  # noqa: E402

# On a GCP VM SECRET_KEY / CRON_SECRET live in Secret Manager, not in .env;
# without this the production check below would refuse to even start the app.
gcp_secrets.load_into_environ(os.environ)

from app import create_app, timeutil  # noqa: E402
from app.config import Config  # noqa: E402
from app.db import get_db  # noqa: E402
from app.repositories import user_repo  # noqa: E402
from app.services import auth_service, task_service  # noqa: E402

# (title, tag, days_from_now or None, already_done, estimate_hours)
# Mix: ~5 overdue, ~4 due today, ~6 due this week, ~5 due later,
#      ~4 no due date, ~6 already done — 30 total, spread across all 3 tags.
# estimate_hours is always set (FEATURE_ESTIMATES needs it to show anything
# at all in the risk radar / "Do this now" card) regardless of whether the
# flag happens to be on for THIS run of the app — the data should already
# be there for whenever it's turned on.
SAMPLE_TASKS = [
    ("Submit DBMS assignment 3", "study", -3, False, 3.0),
    ("Pay hostel mess fee", "personal", -2, False, 0.5),
    ("Return library books", "personal", -1, False, 0.5),
    ("Reply to placement cell email", "work", -1, False, 0.5),
    ("Lab record submission — OS course", "study", -1, False, 2.0),
    ("Team standup notes", "work", 0, False, 0.25),
    ("Buy groceries for the week", "personal", 0, False, 1.0),
    ("Revise OS notes before class", "study", 0, False, 1.5),
    ("Call home", "personal", 0, False, 0.25),
    ("Group project meeting prep", "work", 1, False, 1.0),
    ("Finish LeetCode daily problem", "study", 1, False, 1.0),
    ("Gym session", "personal", 2, False, 1.0),
    ("Review PR from teammate", "work", 2, False, 0.5),
    ("Study for DBMS midterm", "study", 3, False, 5.0),
    ("Clean room before inspection", "personal", 4, False, 1.0),
    ("Attend placement seminar", "work", 5, False, 2.0),
    ("Draft weekly status report", "work", 10, False, 1.5),
    ("Plan weekend trip", "personal", 12, False, 1.0),
    ("Read research paper for seminar", "study", 14, False, 2.0),
    ("Renew gym membership", "personal", 20, False, 0.25),
    ("Organise class notes", "study", None, False, 1.0),
    ("Fix laptop keyboard", "personal", None, False, 1.0),
    ("Update resume", "work", None, False, 2.0),
    ("Explore internship postings", "work", None, False, 1.5),
    ("Submit hackathon registration", "work", -5, True, 0.5),
    ("Finish Python assignment", "study", -4, True, 2.0),
    ("Wash clothes", "personal", -3, True, 1.0),
    ("Attend orientation session", "work", -6, True, 1.0),
    ("Complete DSA practice set 2", "study", -2, True, 2.5),
    ("Book exam hall ticket", "personal", -7, True, 0.5),
]

# From CLAUDE.md section 9's own target ratios for the (not-yet-built)
# --history flag — applied here too, to the handful of tasks this base seed
# already completes, so the per-tag multiplier has something to learn from
# even before --history exists.
ACTUAL_HOURS_RATIO_BY_TAG = {"study": 1.6, "work": 1.3, "personal": 1.1}


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
        db_file = Path(app.config["DATABASE_PATH"]).resolve()
        print(f"Database: {db_file}  (DATABASE_PATH from the environment / .env in the repo root)")
        if app.config["ENV_NAME"] == "production" and (
            len(password) < 12 or any(p in password.lower() for p in Config._PLACEHOLDERS)
        ):
            # The demo login would be a public username/password on the live site.
            sys.exit(
                "Refusing to seed in production with a placeholder SEED_USER_PASSWORD. "
                "Set a real, unguessable SEED_USER_PASSWORD (12+ characters) first."
            )

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

        # Passed regardless of the running app's own FEATURE_ESTIMATES
        # setting — estimate_hours/actual_hours are seeded so the feature
        # has real data to show the moment the flag is turned on, not
        # gated by whether it happens to be on during this seed run.
        estimates_flags = {"estimates": True}

        tz_name = app.config["DEFAULT_TIMEZONE"]
        for title, tag, days_offset, done, estimate_hours in SAMPLE_TASKS:
            task = task_service.create_task(
                conn,
                user_id=user.id,
                title=title,
                tag=tag,
                due_at=build_due_at(days_offset, tz_name),
                estimate_hours=estimate_hours,
                flags=estimates_flags,
            )
            if done:
                actual_hours = round(estimate_hours * ACTUAL_HOURS_RATIO_BY_TAG[tag], 2)
                task_service.complete_task(
                    conn,
                    user_id=user.id,
                    task_id=task["id"],
                    actual_hours=actual_hours,
                    actual_hours_provided=True,
                    flags=estimates_flags,
                )

        print(f"Seeded {len(SAMPLE_TASKS)} tasks across work/study/personal.")


if __name__ == "__main__":
    main()
