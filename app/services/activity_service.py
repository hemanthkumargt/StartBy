"""Write + read the activity log (PRD invariant I5: one row per action, one
row per changed field for updates; a failed write creates none because
every write here happens only after the task write already committed)."""

import sqlite3

from app import timeutil
from app.repositories import activity_repo


def record(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    task_id: int | None,
    action: str,
    field: str | None = None,
    old_value: str | None = None,
    new_value: str | None = None,
) -> None:
    activity_repo.insert(
        conn,
        user_id=user_id,
        task_id=task_id,
        action=action,
        at=timeutil.utcnow_iso(),
        field=field,
        old_value=old_value,
        new_value=new_value,
    )


def serialize_entry(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "task_id": row["task_id"],
        "task_title": row["task_title"],
        "action": row["action"],
        "field": row["field"],
        "old_value": row["old_value"],
        "new_value": row["new_value"],
        "at": row["at"],
    }


def list_activity(
    conn: sqlite3.Connection, user_id: int, *, limit: int = 50, before_id: int | None = None
) -> list[dict]:
    rows = activity_repo.list_for_user(conn, user_id, limit=limit, before_id=before_id)
    return [serialize_entry(row) for row in rows]
