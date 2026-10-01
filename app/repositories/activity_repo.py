"""SQL only — no business rules here (PRD layering rule)."""

import sqlite3


def insert(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    task_id: int | None,
    action: str,
    at: str,
    field: str | None = None,
    old_value: str | None = None,
    new_value: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO activity_log (user_id, task_id, action, field, old_value, new_value, at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, task_id, action, field, old_value, new_value, at),
    )
    conn.commit()


def list_for_user(
    conn: sqlite3.Connection, user_id: int, *, limit: int = 50, before_id: int | None = None
) -> list[sqlite3.Row]:
    sql = "SELECT * FROM activity_log WHERE user_id = ?"
    params: list = [user_id]
    if before_id is not None:
        sql += " AND id < ?"
        params.append(before_id)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    return conn.execute(sql, params).fetchall()


def count_for_task(conn: sqlite3.Connection, task_id: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM activity_log WHERE task_id = ?", (task_id,)
    ).fetchone()
    return row["n"]
