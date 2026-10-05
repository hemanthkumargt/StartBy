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

# I12: risk radar (on-track/amber/red) + "Do this now" card.
RISK_AMBER_WINDOW_HOURS = 24

# --- Phase 2: smart capture (FEATURE_SMART_CAPTURE) ---

CAPTURE_TEXT_MAX_CHARS = 20_000
CAPTURE_PDF_MAX_BYTES = 5 * 1024 * 1024
CAPTURE_PDF_MAX_PAGES = 20
# A syllabus can legitimately hold dozens of deadlines, but an unbounded
# list is a DoS on the confirm path (one INSERT + activity row each).
CAPTURE_MAX_DRAFTS = 25
# Gemini calls cost quota/money: per-user preview budget per window.
CAPTURE_RATE_LIMIT_CALLS = 10
CAPTURE_RATE_LIMIT_WINDOW_SECONDS = 60

# --- Phase 2: overload warning + report card (FEATURE_INSIGHTS) ---

# red tasks are already late to start; amber start within 24h. Thresholds
# are deliberately small — a student rarely has the bandwidth for more.
OVERLOAD_CRITICAL_RED = 4
OVERLOAD_WARNING_RED = 2
OVERLOAD_WARNING_RED_PLUS_AMBER = 4
# Report card: need at least this many completed (estimate, actual) pairs
# before showing a trend, otherwise one lucky task reads as a pattern.
REPORT_MIN_SAMPLES_FOR_TREND = 4
REPORT_SERIES_LIMIT = 12
# An actual/estimate ratio this close to 1.0 counts as "on target".
REPORT_ON_TARGET_BAND = 0.1
# A change in |ln(ratio)| smaller than this is "steady", not a trend.
REPORT_TREND_MIN_CHANGE = 0.05

# Sane window for any stored deadline. A year-0001 or year-9999 due date (a typo,
# or a model's output) overflows datetime arithmetic and then breaks every list
# and the reminder job for everyone.
DUE_YEAR_MIN = 2000
DUE_YEAR_MAX = 2100
# One mistyped "actual hours" (2 -> 20) must not rewrite a user's pace forever:
# each completed task's actual/estimate ratio is clamped to this band before it
# is averaged.
RATIO_CLAMP_MIN = 1 / 3
RATIO_CLAMP_MAX = 3.0
# Tasks overdue longer than this are abandoned, not "overload" or "do this now".
STALE_OVERDUE_DAYS = 7
# The report card says "not enough data" below this many logged tasks.
REPORT_MIN_SAMPLES_FOR_SUMMARY = 3
# Replan "late by" below this is rounding noise, not "late".
REPLAN_LATE_NOISE_HOURS = 5 / 60
