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


def find_start_now_candidates(
    conn: sqlite3.Connection, *, due_before_iso: str
) -> list[sqlite3.Row]:
    """start_by isn't a stored column (I11: computed fresh on every read from
    due_at/estimate/multiplier, never persisted), so this can only narrow
    down to tasks that *could* be red — pending, with both inputs start_by
    needs, not yet reminded, due before the caller's horizon — and leave the
    actual risk check to the service layer, the same split get_dashboard's
    do_this_now already uses. No SQL LIMIT here for the same reason: capping
    before the risk filter could discard true positives in favour of rows
    that turn out not to be due yet. due_before_iso is what keeps this
    bounded instead: a task due further out than the caller's horizon can't
    be red yet regardless of its own estimate, so the due_at index prunes it
    here instead of it being fetched and discarded every run."""
    return conn.execute(
        """
        SELECT tasks.id AS task_id, tasks.title, tasks.status, tasks.due_at,
               tasks.estimate_hours, users.email, users.name AS user_name
        FROM tasks
        JOIN users ON users.id = tasks.user_id
        LEFT JOIN reminders_sent rs ON rs.task_id = tasks.id AND rs.kind = 'start_now'
        WHERE tasks.status = 'pending' AND tasks.deleted_at IS NULL
          AND tasks.due_at IS NOT NULL AND tasks.due_at <= ?
          AND tasks.estimate_hours IS NOT NULL
          AND rs.id IS NULL
        ORDER BY tasks.due_at ASC
        """,
        (due_before_iso,),
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
