"""Extension points for task events.

Empty in Phase 1 by design (PRD section: Extension points). task_service
calls these after every write; Phase 2 plugs estimate tracking in here
without touching Phase 1 code.
"""

from typing import Any


def on_task_created(task: dict[str, Any]) -> None:
    pass


def on_task_updated(task: dict[str, Any], changed_fields: list[str]) -> None:
    pass


def on_task_completed(task: dict[str, Any]) -> None:
    pass
