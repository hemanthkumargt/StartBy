"""Allowed values for columns with a SQLite CHECK constraint.

Kept here too because SQLite CHECK constraints cannot be altered in place —
Phase 2 adds values by rebuilding the table in a new migration, and this
module is what the migration runner and services validate against meanwhile.
"""

TAGS = ("work", "study", "personal")
STATUSES = ("pending", "done")
ACTIVITY_ACTIONS = ("created", "updated", "completed", "reopened", "deleted")
REMINDER_KINDS = ("due_soon", "overdue", "start_now")

TITLE_MAX_LENGTH = 200

# --- Phase 2: effort estimate + start-by time (FEATURE_ESTIMATES) ---

# PRD edge-case checklist: "Estimate of 0, negative, or 500 hours is
# rejected with a clear message" — 0 and negative are always wrong; 100h
# (over 4 days of continuous effort) is a generous but finite upper bound
# for a single task, chosen since the PRD doesn't specify one.
MIN_ESTIMATE_HOURS = 0.25
MAX_ESTIMATE_HOURS = 100

# I13: a user/tag with no completed-task history yet (n=0) gets exactly
# 1.5x — the formula's own neutral starting point, not a separate fallback.
DEFAULT_MULTIPLIER = 1.5
MULTIPLIER_MIN = 1.0
MULTIPLIER_MAX = 3.0

# I10: start_by = due_at - estimate * multiplier * (1 + buffer). The PRD
# names a "buffer" without a value; 15% is a reasonable default margin for
# the unplanned delays a flat effort estimate doesn't account for.
START_BY_BUFFER = 0.15

# I12: risk radar (green/amber/red) + "Do this now" card.
RISK_AMBER_WINDOW_HOURS = 24
