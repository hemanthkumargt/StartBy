"""Voice notes: the dictaphone half of the voice assistant.

A note is just the words the user said (the audio is never kept). It exists so
nothing said out loud gets lost: it can be re-read later and, on request, turned
into tasks through Smart Capture's preview + confirm (I14) — saving a note never
creates a task by itself."""

import re
import sqlite3
from typing import Any

from app.errors import ApiError
from app.repositories import voice_note_repo
from app.validation import require_str

NOTE_MAX_CHARS = 5000
TITLE_MAX_CHARS = 80
MAX_NOTES_PER_USER = 500
LIST_LIMIT = 100

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f​  ⁠﻿]")
_FIRST_SENTENCE = re.compile(r"^(.+?[.!?])(\s|$)")


def _clean(text: str) -> str:
    """Keep paragraph breaks, drop control characters, collapse runs of blanks."""
    text = _CONTROL_CHARS.sub(
        " ", text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
    )
    lines = [" ".join(line.split()) for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def make_title(transcript: str) -> str:
    """First sentence (or the first words), shortened on a word boundary."""
    flat = " ".join(transcript.split())
    match = _FIRST_SENTENCE.match(flat)
    first = (match.group(1) if match else flat).rstrip(".!? ")
    if len(first) <= TITLE_MAX_CHARS:
        return first or "Voice note"
    cut = first[:TITLE_MAX_CHARS].rsplit(" ", 1)[0] or first[:TITLE_MAX_CHARS]
    return cut.rstrip(",;:- ") + "…"


def _public(row: sqlite3.Row, *, full: bool) -> dict[str, Any]:
    transcript = row["transcript"]
    out: dict[str, Any] = {
        "id": row["id"],
        "title": row["title"],
        "created_at": row["created_at"],
        "preview": " ".join(transcript.split())[:140],
    }
    if full:
        out["transcript"] = transcript
    return out


def create_note(conn: sqlite3.Connection, *, user_id: int, transcript: object) -> dict[str, Any]:
    text = _clean(require_str(transcript, "transcript"))
    if not text:
        raise ApiError("validation", "Nothing to save: the note is empty.", 422)
    if len(text) > NOTE_MAX_CHARS:
        raise ApiError("validation", f"A note can be at most {NOTE_MAX_CHARS} characters.", 422)
    if voice_note_repo.count_for_user(conn, user_id) >= MAX_NOTES_PER_USER:
        raise ApiError("limit", "Voice notes are full. Delete some old ones first.", 409)
    note_id = voice_note_repo.create(conn, user_id, make_title(text), text)
    row = voice_note_repo.get(conn, note_id, user_id)
    return _public(row, full=True)


def list_notes(conn: sqlite3.Connection, *, user_id: int) -> list[dict[str, Any]]:
    return [
        _public(r, full=False) for r in voice_note_repo.list_for_user(conn, user_id, LIST_LIMIT)
    ]


def get_note(conn: sqlite3.Connection, *, user_id: int, note_id: int) -> dict[str, Any]:
    row = voice_note_repo.get(conn, note_id, user_id)
    if row is None:
        raise ApiError("not_found", "Voice note not found", 404)
    return _public(row, full=True)


def delete_note(conn: sqlite3.Connection, *, user_id: int, note_id: int) -> None:
    if not voice_note_repo.delete(conn, note_id, user_id):
        raise ApiError("not_found", "Voice note not found", 404)
