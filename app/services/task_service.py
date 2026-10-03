"""Business rules for tasks: validation, status transitions, is_overdue,
and wiring every write into the activity log (routes stay HTTP-only;
repositories stay SQL-only)."""

import sqlite3

from app import timeutil
from app.constants import (
    DEFAULT_MULTIPLIER,
    MAX_ESTIMATE_HOURS,
    MIN_ESTIMATE_HOURS,
    TAGS,
    TITLE_MAX_LENGTH,
)
from app.errors import ApiError
from app.repositories import reminder_repo, task_repo
from app.services import activity_service, estimate_service, hooks
from app.validation import require_str

PATCHABLE_FIELDS = ("title", "notes", "tag", "due_at", "estimate_hours")

# A patchable field with an entry here is only patchable when flags[<value>]
# is on; a field with no entry is always patchable. Name-keyed rather than a
# positional slice of PATCHABLE_FIELDS, so adding a field never depends on
# where it sits in that tuple.
_FIELD_REQUIRES_FLAG = {"estimate_hours": "estimates"}


# I13's per-tag multiplier is learned from (tag, estimate_hours, actual_hours)
# triples recorded at completion time. estimate_hours and tag are both
# inputs to that pairing, so editing either one on an already-done task
# would silently rewrite history the multiplier already learned from —
# unlike a pending task, where there's no history yet to corrupt.
_FIELDS_LOCKED_AFTER_COMPLETION = frozenset({"estimate_hours", "tag"})


def _field_is_patchable(name: str, flags: dict, status: str) -> bool:
    if name not in PATCHABLE_FIELDS:
        return False
    if status == "done" and name in _FIELDS_LOCKED_AFTER_COMPLETION:
        return False
    required_flag = _FIELD_REQUIRES_FLAG.get(name)
    return required_flag is None or flags.get(required_flag, False)


def _validate_title(title: object) -> str:
    title = require_str(title, "title").strip()
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


def _validate_hours(value: object, field_name: str) -> float | None:
    """Shared by estimate_hours and actual_hours — same unit, same
    realistic range."""
    if value is None or value == "":
        return None
    # bool is a subclass of int in Python, so it must be excluded explicitly
    # or True/False would silently pass as 1.0/0.0.
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ApiError("validation", f"{field_name} must be a number", 422)
    value = float(value)
    if not (MIN_ESTIMATE_HOURS <= value <= MAX_ESTIMATE_HOURS):
        raise ApiError(
            "validation",
            f"{field_name} must be between {MIN_ESTIMATE_HOURS} and {MAX_ESTIMATE_HOURS}",
            422,
        )
    return value


def _multipliers_for(conn: sqlite3.Connection, user_id: int, flags: dict) -> dict[str, float]:
    """I13's per-tag multiplier, computed once per request (not once per
    task — every task of the same tag would otherwise redo the identical
    history query) and skipped entirely when the flag is off."""
    if not flags.get("estimates", False):
        return {}
    return estimate_service.multipliers_by_tag(
        task_repo.estimate_actual_pairs_for_user(conn, user_id)
    )


def serialize_task(
    row: sqlite3.Row, *, flags: dict | None = None, multipliers: dict[str, float] | None = None
) -> dict:
    flags = flags or {}
    multipliers = multipliers or {}
    is_overdue = (
        row["status"] == "pending"
        and row["due_at"] is not None
        and timeutil.is_before_now(row["due_at"])
    )
    task = {
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
    if flags.get("estimates", False):
        # I15: these keys only exist when the flag is on, so a flags-off
        # response is byte-identical to v1.0's shape, not just its values.
        start_by = None
        if row["estimate_hours"] is not None:
            # I13: a tag with no completed-task history (no key in
            # multipliers) falls back to DEFAULT_MULTIPLIER — exactly what
            # multiplier_from_history(0, 0.0) would compute anyway, just
            # without redoing that lookup for every task of the tag.
            multiplier = multipliers.get(row["tag"], DEFAULT_MULTIPLIER)
            start_by = estimate_service.compute_start_by(
                row["due_at"], row["estimate_hours"], multiplier
            )
        task["estimate_hours"] = row["estimate_hours"]
        task["actual_hours"] = row["actual_hours"]
        task["start_by"] = start_by
        # I12 risk radar. Adaptive Replanning (CLAUDE.md 2.5): risk is always
        # computed fresh from the current status/start_by (never stored), so
        # a missed start time shows up as "red" on the very next read, the
        # same way is_overdue already does for due_at — no separate
        # recompute step, and freezegun-testable since it goes through
        # timeutil here instead of comparing dates in JS.
        task["risk"] = estimate_service.compute_risk(row["status"], start_by)
    return task


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
    estimate_hours: object = None,
    flags: dict | None = None,
) -> dict:
    flags = flags or {}
    title = _validate_title(title)
    tag = _validate_tag(tag) if tag is not None else "personal"
    due_at = _validate_due_at(due_at)
    notes = require_str(notes, "notes").strip() or None
    estimate_hours = (
        _validate_hours(estimate_hours, "estimate_hours") if flags.get("estimates", False) else None
    )

    row = task_repo.create(
        conn,
        user_id=user_id,
        title=title,
        notes=notes,
        tag=tag,
        due_at=due_at,
        created_at=timeutil.utcnow_iso(),
        estimate_hours=estimate_hours,
    )
    activity_service.record(conn, user_id=user_id, task_id=row["id"], action="created")

    task = serialize_task(row, flags=flags, multipliers=_multipliers_for(conn, user_id, flags))
    hooks.on_task_created(task)
    return task


def get_task(
    conn: sqlite3.Connection, *, user_id: int, task_id: int, flags: dict | None = None
) -> dict:
    flags = flags or {}
    row = _get_active_or_404(conn, user_id, task_id)
    return serialize_task(row, flags=flags, multipliers=_multipliers_for(conn, user_id, flags))


def list_tasks(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    status: str | None = None,
    tag: str | None = None,
    q: str | None = None,
    flags: dict | None = None,
) -> list[dict]:
    flags = flags or {}
    if status is not None and status not in ("pending", "done"):
        raise ApiError("validation", "status must be 'pending' or 'done'", 422)
    if tag is not None and tag not in TAGS:
        raise ApiError("validation", f"tag must be one of {', '.join(TAGS)}", 422)

    rows = task_repo.list_active_for_user(conn, user_id, status=status, tag=tag, q=q)
    multipliers = _multipliers_for(conn, user_id, flags)
    return [serialize_task(row, flags=flags, multipliers=multipliers) for row in rows]


def update_task(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    task_id: int,
    fields: dict,
    flags: dict | None = None,
) -> dict:
    flags = flags or {}
    row = _get_active_or_404(conn, user_id, task_id)

    updates: dict = {}
    changes: list[tuple[str, object, object]] = []

    for name, value in fields.items():
        if not _field_is_patchable(name, flags, row["status"]):
            continue
        if name == "title":
            value = _validate_title(value)
        elif name == "tag":
            value = _validate_tag(value)
        elif name == "due_at":
            value = _validate_due_at(value)
        elif name == "notes":
            value = require_str(value, "notes").strip() or None
        elif name == "estimate_hours":
            value = _validate_hours(value, "estimate_hours")

        old_value = row[name]
        if value != old_value:
            updates[name] = value
            changes.append((name, old_value, value))

    if not updates:
        return serialize_task(row, flags=flags, multipliers=_multipliers_for(conn, user_id, flags))

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

    if "due_at" in updates or "estimate_hours" in updates or "tag" in updates:
        # I8/I11: a new deadline, a new estimate, OR a new tag can move
        # start_by (I10: start_by = due_at - estimate * multiplier * buffer,
        # and multiplier is looked up per tag per I13), so the old
        # due_soon/overdue/start_now reminder records for this task no
        # longer apply to whatever start_by now is.
        reminder_repo.clear_for_task(conn, task_id)

    task = serialize_task(
        updated_row, flags=flags, multipliers=_multipliers_for(conn, user_id, flags)
    )
    hooks.on_task_updated(task, [c[0] for c in changes])
    return task


def complete_task(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    task_id: int,
    actual_hours: object = None,
    actual_hours_provided: bool = False,
    flags: dict | None = None,
) -> dict:
    flags = flags or {}
    row = _get_active_or_404(conn, user_id, task_id)
    # actual_hours_provided distinguishes "no value this time" (e.g. a
    # reopen-then-recomplete where the user skipped the prompt) from
    # "explicitly cleared" — a reopen that was only fixing a typo shouldn't
    # silently wipe a previously-recorded actual_hours just because this
    # completion didn't re-enter one.
    update_actual_hours = flags.get("estimates", False) and actual_hours_provided
    validated_actual_hours = (
        _validate_hours(actual_hours, "actual_hours") if update_actual_hours else None
    )

    if row["status"] == "done":
        if update_actual_hours and validated_actual_hours != row["actual_hours"]:
            # A repeat /complete call on an already-done task (a retried
            # request, the dialog answered from a second tab) still carries
            # a real value worth keeping, not the ordinary no-op below.
            updated_row = task_repo.update_actual_hours(
                conn, task_id, actual_hours=validated_actual_hours, updated_at=timeutil.utcnow_iso()
            )
            activity_service.record(
                conn,
                user_id=user_id,
                task_id=task_id,
                action="updated",
                field="actual_hours",
                old_value=None if row["actual_hours"] is None else str(row["actual_hours"]),
                new_value=str(validated_actual_hours),
            )
            return serialize_task(
                updated_row, flags=flags, multipliers=_multipliers_for(conn, user_id, flags)
            )
        return serialize_task(row, flags=flags, multipliers=_multipliers_for(conn, user_id, flags))

    now = timeutil.utcnow_iso()
    updated_row = task_repo.complete(
        conn,
        task_id,
        completed_at=now,
        updated_at=now,
        actual_hours=validated_actual_hours,
        update_actual_hours=update_actual_hours,
    )
    activity_service.record(conn, user_id=user_id, task_id=task_id, action="completed")

    # Computed after the write: this completion's own actual_hours (if any)
    # is part of the history a sibling task of the same tag should see in
    # this same response, not just on the next read.
    task = serialize_task(
        updated_row, flags=flags, multipliers=_multipliers_for(conn, user_id, flags)
    )
    hooks.on_task_completed(task)
    return task


def reopen_task(
    conn: sqlite3.Connection, *, user_id: int, task_id: int, flags: dict | None = None
) -> dict:
    flags = flags or {}
    row = _get_active_or_404(conn, user_id, task_id)
    if row["status"] == "pending":
        return serialize_task(row, flags=flags, multipliers=_multipliers_for(conn, user_id, flags))

    updated_row = task_repo.set_status(
        conn, task_id, status="pending", completed_at=None, updated_at=timeutil.utcnow_iso()
    )
    activity_service.record(conn, user_id=user_id, task_id=task_id, action="reopened")

    # I8: reopening re-activates whatever due_at the task already had, so a
    # still-overdue reopened task must be able to remind again too — same
    # reasoning as update_task's due_at branch, not just a due_at change.
    reminder_repo.clear_for_task(conn, task_id)

    return serialize_task(
        updated_row, flags=flags, multipliers=_multipliers_for(conn, user_id, flags)
    )


def delete_task(conn: sqlite3.Connection, *, user_id: int, task_id: int) -> None:
    _get_active_or_404(conn, user_id, task_id)
    task_repo.soft_delete(conn, task_id, deleted_at=timeutil.utcnow_iso())
    activity_service.record(conn, user_id=user_id, task_id=task_id, action="deleted")


def get_dashboard(conn: sqlite3.Connection, *, user_id: int, flags: dict | None = None) -> dict:
    flags = flags or {}
    multipliers = _multipliers_for(conn, user_id, flags)
    counts = task_repo.counts_for_user(conn, user_id, now_iso=timeutil.utcnow_iso())
    due_next = [
        serialize_task(row, flags=flags, multipliers=multipliers)
        for row in task_repo.due_next_for_user(conn, user_id)
    ]
    dashboard = {**counts, "due_next": due_next}
    if flags.get("estimates", False):
        # "Do this now" needs every pending task's risk, not just the ones
        # with a due_at (due_next's own query), since risk comes from
        # start_by rather than due_at directly.
        pending = [
            serialize_task(row, flags=flags, multipliers=multipliers)
            for row in task_repo.list_active_for_user(conn, user_id, status="pending")
        ]
        dashboard["do_this_now"] = estimate_service.pick_do_this_now(pending)
    return dashboard
