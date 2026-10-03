-- Phase 2: per-tag estimate-correction multiplier (FEATURE_ESTIMATES),
-- I13. Records how long a task actually took, set once via the "one-tap"
-- prompt on completion; history of (estimate_hours, actual_hours) pairs
-- per user/tag feeds multiplier_from_history to correct future start_by
-- recommendations for that tag.
ALTER TABLE tasks ADD COLUMN actual_hours REAL;
