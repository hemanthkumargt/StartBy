-- Google Calendar sync (per-user OAuth). calendar_links holds the refresh
-- token a user granted (scope: calendar.events only); calendar_events maps a
-- task to the event created for it so later edits patch it instead of adding
-- a duplicate, and completing/deleting the task removes it.
CREATE TABLE calendar_links (
    user_id       INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    refresh_token TEXT NOT NULL,
    connected_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE calendar_events (
    task_id  INTEGER PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
    user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    event_id TEXT NOT NULL
);
CREATE INDEX idx_calendar_events_user ON calendar_events(user_id);
