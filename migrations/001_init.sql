PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE schema_migrations (
  version    TEXT PRIMARY KEY,
  applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE users (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  name          TEXT NOT NULL,
  email         TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  timezone      TEXT NOT NULL DEFAULT 'Asia/Kolkata',
  dark_mode     INTEGER NOT NULL DEFAULT 0,
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE tasks (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title        TEXT NOT NULL,
  notes        TEXT,
  tag          TEXT NOT NULL DEFAULT 'personal'
               CHECK (tag IN ('work','study','personal')),
  status       TEXT NOT NULL DEFAULT 'pending'
               CHECK (status IN ('pending','done')),
  due_at       TEXT,
  created_at   TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at   TEXT NOT NULL DEFAULT (datetime('now')),
  completed_at TEXT,
  deleted_at   TEXT
);
CREATE INDEX idx_tasks_user_status_due ON tasks(user_id, status, due_at);
CREATE INDEX idx_tasks_due ON tasks(status, due_at);

CREATE TABLE activity_log (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  task_id   INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
  action    TEXT NOT NULL CHECK (action IN
            ('created','updated','completed','reopened','deleted')),
  field     TEXT,
  old_value TEXT,
  new_value TEXT,
  at        TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_activity_user_at ON activity_log(user_id, at DESC);

CREATE TABLE reminders_sent (
  id      INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  kind    TEXT NOT NULL CHECK (kind IN ('due_soon','overdue')),
  sent_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (task_id, kind)
);
