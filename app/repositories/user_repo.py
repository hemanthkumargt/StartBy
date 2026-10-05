"""SQL only — no business rules here (PRD layering rule)."""

import sqlite3


def create(
    conn: sqlite3.Connection,
    *,
    name: str,
    email: str,
    password_hash: str,
    timezone: str,
    created_at: str,
) -> sqlite3.Row:
    cur = conn.execute(
        """
        INSERT INTO users (name, email, password_hash, timezone, dark_mode, created_at)
        VALUES (?, ?, ?, ?, 1, ?)
        RETURNING *
        """,
        (name, email, password_hash, timezone, created_at),
    )
    row = cur.fetchone()
    conn.commit()
    return row


def find_by_email(conn: sqlite3.Connection, email: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()


def find_by_id(conn: sqlite3.Connection, user_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def update_settings(
    conn: sqlite3.Connection, user_id: int, *, dark_mode: int, timezone: str
) -> sqlite3.Row | None:
    """Pure write: both values are final (the "keep existing value if
    omitted" merge is a business rule and lives in user_service, not here)."""
    cur = conn.execute(
        "UPDATE users SET dark_mode = ?, timezone = ? WHERE id = ? RETURNING *",
        (dark_mode, timezone, user_id),
    )
    row = cur.fetchone()
    conn.commit()
    return row


def delete_by_email(conn: sqlite3.Connection, email: str) -> None:
    """Cascades to that user's tasks, activity log and reminders_sent rows
    (ON DELETE CASCADE in 001_init.sql) — used by scripts/seed.py --reset."""
    conn.execute("DELETE FROM users WHERE email = ?", (email,))
    conn.commit()


def update_profile(
    conn: sqlite3.Connection, user_id: int, *, name: str, email: str
) -> sqlite3.Row | None:
    """Update the user's display name and email address."""
    cur = conn.execute(
        "UPDATE users SET name = ?, email = ? WHERE id = ? RETURNING *",
        (name, email, user_id),
    )
    row = cur.fetchone()
    conn.commit()
    return row


def update_assistant_name(
    conn: sqlite3.Connection, user_id: int, assistant_name: str | None
) -> sqlite3.Row | None:
    cur = conn.execute(
        "UPDATE users SET assistant_name = ? WHERE id = ? RETURNING *", (assistant_name, user_id)
    )
    row = cur.fetchone()
    conn.commit()
    return row
