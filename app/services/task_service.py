"""Business rules for tasks: validation, status transitions, is_overdue,
and wiring every write into the activity log (routes stay HTTP-only;
repositories stay SQL-only)."""

import sqlite3

from app import timeutil
from app.constants import TAGS, TITLE_MAX_LENGTH
from app.errors import ApiError
from app.repositories import reminder_repo, task_repo
from app.services import activity_service, hooks

PATCHABLE_FIELDS = ("title", "notes", "tag", "due_at")


def _validate_title(title: str) -> str:
    title = (title or "").strip()
    if not title:
        raise ApiError("validation", "Title is required", 422)
    if len(title) > TITLE_MAX_LENGTH:
        raise ApiError("validation", f"Title must be at most {TITLE_MAX_LENGTH} characters", 422)
    return title


def _validate_tag(tag: str) -> str:
    if tag not in TAGS:
        raise ApiError("validation", f"Tag must be one of {', '.join(TAGS)}", 422)
    return tag


def _validate_due_at(due_at: str | None) -> str | None:
    if due_at is None or due_at == "":
        return None
    try:
        return timeutil.normalize_due_at(due_at)
    except ValueError as exc:
        raise ApiError("validation", "due_at must be a valid ISO-8601 datetime", 422) from exc


def serialize_task(row: sqlite3.Row) -> dict:
    is_overdue = (
        row["status"] == "pending"
        and row["due_at"] is not None
        and timeutil.is_before_now(row["due_at"])
    )
    return {
        "id": row["id"],
        "title": row["title"],
        "notes": row["notes"],
        "tag": row["tag"],
        "status": row["status"],
        "due_at": row["due_at"],
        "is_overdue": is_overdue,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "completed_at": row["completed_at"],
    }


def _get_active_or_404(conn: sqlite3.Connection, user_id: int, task_id: int) -> sqlite3.Row:
    row = task_repo.find_active_for_user(conn, user_id, task_id)
    if row is None:
        raise ApiError("not_found", "Task not found", 404)
    return row


def create_task(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    title: str,
    notes: str | None = None,
    tag: str | None = None,
    due_at: str | None = None,
) -> dict:
    title = _validate_title(title)
    tag = _validate_tag(tag) if tag is not None else "personal"
    due_at = _validate_due_at(due_at)
    notes = (notes or "").strip() or None

    row = task_repo.create(
        conn,
        user_id=user_id,
        title=title,
        notes=notes,
        tag=tag,
        due_at=due_at,
        created_at=timeutil.utcnow_iso(),
    )
    activity_service.record(conn, user_id=user_id, task_id=row["id"], action="created")

    task = serialize_task(row)
    hooks.on_task_created(task)
    return task


def get_task(conn: sqlite3.Connection, *, user_id: int, task_id: int) -> dict:
    return serialize_task(_get_active_or_404(conn, user_id, task_id))


def list_tasks(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    status: str | None = None,
    tag: str | None = None,
    q: str | None = None,
) -> list[dict]:
    if status is not None and status not in ("pending", "done"):
        raise ApiError("validation", "status must be 'pending' or 'done'", 422)
    if tag is not None and tag not in TAGS:
        raise ApiError("validation", f"tag must be one of {', '.join(TAGS)}", 422)

    rows = task_repo.list_active_for_user(conn, user_id, status=status, tag=tag, q=q)
    return [serialize_task(row) for row in rows]


def update_task(conn: sqlite3.Connection, *, user_id: int, task_id: int, fields: dict) -> dict:
    row = _get_active_or_404(conn, user_id, task_id)

    updates: dict = {}
    changes: list[tuple[str, object, object]] = []

    for name, value in fields.items():
        if name not in PATCHABLE_FIELDS:
            continue
        if name == "title":
            value = _validate_title(value)
        elif name == "tag":
            value = _validate_tag(value)
        elif name == "due_at":
            value = _validate_due_at(value)
        elif name == "notes":
            value = (value or "").strip() or None

        old_value = row[name]
        if value != old_value:
            updates[name] = value
            changes.append((name, old_value, value))

    if not updates:
        return serialize_task(row)

    updated_row = task_repo.update_fields(conn, task_id, updates, updated_at=timeutil.utcnow_iso())

    for field, old_value, new_value in changes:
        activity_service.record(
            conn,
            user_id=user_id,
            task_id=task_id,
            action="updated",
            field=field,
            old_value=None if old_value is None else str(old_value),
            new_value=None if new_value is None else str(new_value),
        )

    if "due_at" in updates:
        # I8: a new deadline can remind again, so the old due_soon/overdue
        # reminder records for this task no longer apply.
        reminder_repo.clear_for_task(conn, task_id)

    task = serialize_task(updated_row)
    hooks.on_task_updated(task, [c[0] for c in changes])
    return task


def complete_task(conn: sqlite3.Connection, *, user_id: int, task_id: int) -> dict:
    row = _get_active_or_404(conn, user_id, task_id)
    if row["status"] == "done":
        return serialize_task(row)

    now = timeutil.utcnow_iso()
    updated_row = task_repo.set_status(
        conn, task_id, status="done", completed_at=now, updated_at=now
    )
    activity_service.record(conn, user_id=user_id, task_id=task_id, action="completed")

    task = serialize_task(updated_row)
    hooks.on_task_completed(task)
    return task


def reopen_task(conn: sqlite3.Connection, *, user_id: int, task_id: int) -> dict:
    row = _get_active_or_404(conn, user_id, task_id)
    if row["status"] == "pending":
        return serialize_task(row)

    updated_row = task_repo.set_status(
        conn, task_id, status="pending", completed_at=None, updated_at=timeutil.utcnow_iso()
    )
    activity_service.record(conn, user_id=user_id, task_id=task_id, action="reopened")
    return serialize_task(updated_row)


def delete_task(conn: sqlite3.Connection, *, user_id: int, task_id: int) -> None:
    _get_active_or_404(conn, user_id, task_id)
    task_repo.soft_delete(conn, task_id, deleted_at=timeutil.utcnow_iso())
    activity_service.record(conn, user_id=user_id, task_id=task_id, action="deleted")


def get_dashboard(conn: sqlite3.Connection, *, user_id: int) -> dict:
    counts = task_repo.counts_for_user(conn, user_id, now_iso=timeutil.utcnow_iso())
    due_next = [serialize_task(row) for row in task_repo.due_next_for_user(conn, user_id)]
    return {**counts, "due_next": due_next}
