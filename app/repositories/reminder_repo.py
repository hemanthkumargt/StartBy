"""SQL only — no business rules here (PRD layering rule)."""

import sqlite3


def find_due_soon_candidates(
    conn: sqlite3.Connection, *, now_iso: str, window_end_iso: str, limit: int
) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT tasks.id AS task_id, tasks.title, users.email, users.name AS user_name
        FROM tasks
        JOIN users ON users.id = tasks.user_id
        LEFT JOIN reminders_sent rs ON rs.task_id = tasks.id AND rs.kind = 'due_soon'
        WHERE tasks.status = 'pending' AND tasks.deleted_at IS NULL
          AND tasks.due_at IS NOT NULL
          AND tasks.due_at >= ? AND tasks.due_at <= ?
          AND rs.id IS NULL
        ORDER BY tasks.due_at ASC
        LIMIT ?
        """,
        (now_iso, window_end_iso, limit),
    ).fetchall()


def find_overdue_candidates(
    conn: sqlite3.Connection, *, now_iso: str, limit: int
) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT tasks.id AS task_id, tasks.title, users.email, users.name AS user_name
        FROM tasks
        JOIN users ON users.id = tasks.user_id
        LEFT JOIN reminders_sent rs ON rs.task_id = tasks.id AND rs.kind = 'overdue'
        WHERE tasks.status = 'pending' AND tasks.deleted_at IS NULL
          AND tasks.due_at IS NOT NULL AND tasks.due_at < ?
          AND rs.id IS NULL
        ORDER BY tasks.due_at ASC
        LIMIT ?
        """,
        (now_iso, limit),
    ).fetchall()


def record_sent(conn: sqlite3.Connection, task_id: int, kind: str) -> None:
    # UNIQUE(task_id, kind) backs invariant I7 even under concurrent/overlapping runs.
    conn.execute(
        "INSERT OR IGNORE INTO reminders_sent (task_id, kind) VALUES (?, ?)", (task_id, kind)
    )
    conn.commit()


def clear_for_task(conn: sqlite3.Connection, task_id: int) -> None:
    conn.execute("DELETE FROM reminders_sent WHERE task_id = ?", (task_id,))
    conn.commit()
