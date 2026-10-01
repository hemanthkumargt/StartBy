"""SQL only — no business rules here (PRD layering rule)."""

import sqlite3


def create(
    conn: sqlite3.Connection, *, name: str, email: str, password_hash: str, timezone: str
) -> sqlite3.Row:
    cur = conn.execute(
        """
        INSERT INTO users (name, email, password_hash, timezone)
        VALUES (?, ?, ?, ?)
        RETURNING id, name, email, password_hash, timezone, dark_mode, created_at
        """,
        (name, email, password_hash, timezone),
    )
    row = cur.fetchone()
    conn.commit()
    return row


def find_by_email(conn: sqlite3.Connection, email: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM users WHERE email = ?", (email,)
    ).fetchone()


def find_by_id(conn: sqlite3.Connection, user_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM users WHERE id = ?", (user_id,)
    ).fetchone()


def update_settings(
    conn: sqlite3.Connection, user_id: int, *, dark_mode: bool | None, timezone: str | None
) -> sqlite3.Row | None:
    row = find_by_id(conn, user_id)
    if row is None:
        return None
    new_dark_mode = int(dark_mode) if dark_mode is not None else row["dark_mode"]
    new_timezone = timezone if timezone is not None else row["timezone"]
    conn.execute(
        "UPDATE users SET dark_mode = ?, timezone = ? WHERE id = ?",
        (new_dark_mode, new_timezone, user_id),
    )
    conn.commit()
    return find_by_id(conn, user_id)
