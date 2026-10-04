-- Voice notes: what the user said (the transcript), kept as a note. The audio
-- itself is never stored: it is large, sensitive, and not needed once it has
-- been turned into text.
CREATE TABLE voice_notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title      TEXT NOT NULL,
    transcript TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now'))
);
CREATE INDEX idx_voice_notes_user ON voice_notes(user_id, created_at DESC, id DESC);
