"""Allowed values for columns with a SQLite CHECK constraint.

Kept here too because SQLite CHECK constraints cannot be altered in place —
Phase 2 adds values by rebuilding the table in a new migration, and this
module is what the migration runner and services validate against meanwhile.
"""

TAGS = ("work", "study", "personal")
STATUSES = ("pending", "done")
ACTIVITY_ACTIONS = ("created", "updated", "completed", "reopened", "deleted")
REMINDER_KINDS = ("due_soon", "overdue")

TITLE_MAX_LENGTH = 200
