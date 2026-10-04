"""Extension points for task events (PRD: Extension points).

task_service fires one of these after every successful write. Anything that
reacts to task changes — Pub/Sub/BigQuery event export, Cloud Tasks
scheduling, calendar sync — registers a listener here instead of task_service
knowing about it. A listener that raises is logged and skipped: a failing
integration must never fail the user's request, and must not stop the other
listeners from running."""

import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class TaskListener(Protocol):
    def on_task_created(self, task: dict[str, Any], *, user_id: int) -> None: ...

    def on_task_updated(
        self, task: dict[str, Any], changed_fields: list[str], *, user_id: int
    ) -> None: ...

    def on_task_completed(self, task: dict[str, Any], *, user_id: int) -> None: ...

    def on_task_reopened(self, task: dict[str, Any], *, user_id: int) -> None: ...

    def on_task_deleted(self, task_id: int, *, user_id: int) -> None: ...


_listeners: list[Any] = []


def register(listener: Any) -> None:
    _listeners.append(listener)


def clear() -> None:
    """For tests and app re-creation: listeners belong to one app instance."""
    _listeners.clear()


def _fire(event: str, *args: Any, **kwargs: Any) -> None:
    for listener in list(_listeners):
        handler = getattr(listener, event, None)
        if handler is None:
            continue
        try:
            handler(*args, **kwargs)
        except Exception:  # noqa: BLE001 — see module docstring
            logger.exception("task_listener_failed event=%s", event)


def on_task_created(task: dict[str, Any], *, user_id: int) -> None:
    _fire("on_task_created", task, user_id=user_id)


def on_task_updated(task: dict[str, Any], changed_fields: list[str], *, user_id: int) -> None:
    _fire("on_task_updated", task, changed_fields, user_id=user_id)


def on_task_completed(task: dict[str, Any], *, user_id: int) -> None:
    _fire("on_task_completed", task, user_id=user_id)


def on_task_reopened(task: dict[str, Any], *, user_id: int) -> None:
    _fire("on_task_reopened", task, user_id=user_id)


def on_task_deleted(task_id: int, *, user_id: int) -> None:
    _fire("on_task_deleted", task_id, user_id=user_id)
