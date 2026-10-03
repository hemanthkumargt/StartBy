-- Phase 2: effort estimate + start-by time (FEATURE_ESTIMATES).
-- Additive only: a new nullable column, no renames or drops, per the
-- safety practice in PRD.md / CLAUDE.md. Flags-off behaviour is unaffected
-- since this column is simply never read when FEATURE_ESTIMATES is off.

ALTER TABLE tasks ADD COLUMN estimate_hours REAL;
