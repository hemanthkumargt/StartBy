-- Phase 2: start-now reminders need a third reminders_sent.kind value.
-- SQLite can't ALTER a CHECK constraint in place, so the table is rebuilt
-- with the widened list and every existing row carried across unchanged.
-- Wrapped in one explicit transaction (SQLite DDL is fully transactional)
-- so a crash between DROP and RENAME rolls back to the pre-migration
-- table instead of leaving reminders_sent permanently gone and the next
-- boot's retry unable to complete (CREATE TABLE ..._new would collide
-- with a half-applied previous attempt).
BEGIN TRANSACTION;

CREATE TABLE reminders_sent_new (
  id      INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  kind    TEXT NOT NULL CHECK (kind IN ('due_soon','overdue','start_now')),
  sent_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (task_id, kind)
);

INSERT INTO reminders_sent_new (id, task_id, kind, sent_at)
SELECT id, task_id, kind, sent_at FROM reminders_sent;

DROP TABLE reminders_sent;
ALTER TABLE reminders_sent_new RENAME TO reminders_sent;

COMMIT;
