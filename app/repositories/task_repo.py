"""SQL only — no business rules here (PRD layering rule)."""

import sqlite3

ORDER_BY = """
    ORDER BY
      CASE status WHEN 'pending' THEN 0 ELSE 1 END,
      CASE WHEN due_at IS NULL THEN 1 ELSE 0 END,
      due_at ASC,
      id ASC
"""


def create(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    title: str,
    notes: str | None,
    tag: str,
    due_at: str | None,
    created_at: str,
) -> sqlite3.Row:
    cur = conn.execute(
        """
        INSERT INTO tasks (user_id, title, notes, tag, due_at, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        RETURNING *
        """,
        (user_id, title, notes, tag, due_at, created_at, created_at),
    )
    row = cur.fetchone()
    conn.commit()
    return row


def find_active_for_user(
    conn: sqlite3.Connection, user_id: int, task_id: int
) -> sqlite3.Row | None:
    """A task is 'findable' only while it belongs to this user and is not
    soft-deleted — the same lookup that backs both reads and writes, so a
    deleted or someone-else's task behaves identically (404), never 403."""
    return conn.execute(
        "SELECT * FROM tasks WHERE id = ? AND user_id = ? AND deleted_at IS NULL",
        (task_id, user_id),
    ).fetchone()


def list_active_for_user(
    conn: sqlite3.Connection,
    user_id: int,
    *,
    status: str | None = None,
    tag: str | None = None,
    q: str | None = None,
) -> list[sqlite3.Row]:
    sql = "SELECT * FROM tasks WHERE user_id = ? AND deleted_at IS NULL"
    params: list = [user_id]

    if status is not None:
        sql += " AND status = ?"
        params.append(status)
    if tag is not None:
        sql += " AND tag = ?"
        params.append(tag)
    if q:
        sql += " AND title LIKE ? ESCAPE '\\'"
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        params.append(f"%{escaped}%")

    sql += ORDER_BY
    return conn.execute(sql, params).fetchall()


def update_fields(
    conn: sqlite3.Connection, task_id: int, fields: dict, *, updated_at: str
) -> sqlite3.Row:
    assignments = ", ".join(f"{name} = ?" for name in fields)
    params = [*fields.values(), updated_at, task_id]
    conn.execute(
        f"UPDATE tasks SET {assignments}, updated_at = ? WHERE id = ?",
        params,
    )
    conn.commit()
    return conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()


def set_status(
    conn: sqlite3.Connection,
    task_id: int,
    *,
    status: str,
    completed_at: str | None,
    updated_at: str,
) -> sqlite3.Row:
    conn.execute(
        "UPDATE tasks SET status = ?, completed_at = ?, updated_at = ? WHERE id = ?",
        (status, completed_at, updated_at, task_id),
    )
    conn.commit()
    return conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()


def soft_delete(conn: sqlite3.Connection, task_id: int, *, deleted_at: str) -> None:
    conn.execute("UPDATE tasks SET deleted_at = ? WHERE id = ?", (deleted_at, task_id))
    conn.commit()


def counts_for_user(conn: sqlite3.Connection, user_id: int, *, now_iso: str) -> dict[str, int]:
    row = conn.execute(
        """
        SELECT
          COUNT(*) AS total,
          SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) AS completed,
          SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending,
          SUM(CASE WHEN status = 'pending' AND due_at IS NOT NULL AND due_at < ?
                   THEN 1 ELSE 0 END) AS overdue
        FROM tasks
        WHERE user_id = ? AND deleted_at IS NULL
        """,
        (now_iso, user_id),
    ).fetchone()
    return {
        "total": row["total"] or 0,
        "completed": row["completed"] or 0,
        "pending": row["pending"] or 0,
        "overdue": row["overdue"] or 0,
    }


def due_next_for_user(
    conn: sqlite3.Connection, user_id: int, *, limit: int = 5
) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT * FROM tasks
        WHERE user_id = ? AND deleted_at IS NULL AND status = 'pending' AND due_at IS NOT NULL
        ORDER BY due_at ASC
        LIMIT ?
        """,
        (user_id, limit),
    ).fetchall()
