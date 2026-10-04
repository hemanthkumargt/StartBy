"""Smart capture (Phase 2): turn pasted text or a PDF into *draft* tasks.

Invariant I14 — nothing here writes to the database until confirm(): preview()
only returns drafts, and confirm() saves exactly the rows the client sends
(the ticked ones), each re-validated by task_service like any other create.

Two producers feed preview(): Gemini (gemini_client) and a regex/dateparser
fallback. Gemini's output is untrusted text, so both producers' drafts pass
through the same sanitize_draft() before anyone sees them."""

import logging
import re
import sqlite3
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app import timeutil
from app.constants import (
    CAPTURE_MAX_DRAFTS,
    CAPTURE_PDF_MAX_BYTES,
    CAPTURE_RATE_LIMIT_CALLS,
    CAPTURE_RATE_LIMIT_WINDOW_SECONDS,
    CAPTURE_TEXT_MAX_CHARS,
    DUE_YEAR_MAX,
    DUE_YEAR_MIN,
    MAX_ESTIMATE_HOURS,
    MIN_ESTIMATE_HOURS,
    TAGS,
    TITLE_MAX_LENGTH,
)
from app.errors import ApiError
from app.ratelimit import RateLimiter
from app.services import fallback_extractor, gemini_client, pdf_extract, task_service
from app.validation import require_str

logger = logging.getLogger(__name__)

_NOTES_MAX_CHARS = 500
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


rate_limiter = RateLimiter(CAPTURE_RATE_LIMIT_CALLS, CAPTURE_RATE_LIMIT_WINDOW_SECONDS)
# Its own budget: a dictation is a transcribe call PLUS a preview call, and sharing one
# limiter halved the number of dictations a minute.
transcribe_limiter = RateLimiter(CAPTURE_RATE_LIMIT_CALLS, CAPTURE_RATE_LIMIT_WINDOW_SECONDS)


def extract_pdf_text(data: bytes) -> str:
    if len(data) > CAPTURE_PDF_MAX_BYTES:
        raise ApiError("validation", "PDF is larger than 5 MB", 413)
    if not data.startswith(b"%PDF"):
        raise ApiError("validation", "File is not a PDF", 422)
    try:
        text = pdf_extract.extract_text(data)
    except pdf_extract.PdfEncrypted as exc:
        raise ApiError("validation", "Password-protected PDFs are not supported", 422) from exc
    except pdf_extract.PdfUnreadable as exc:
        logger.warning("pdf_parse_failed error=%s", exc)
        raise ApiError("validation", "Could not read this PDF", 422) from exc
    if not text.strip():
        raise ApiError(
            "validation",
            "No selectable text found in this PDF (scanned images are not supported)",
            422,
        )
    return text


def _clean_text(value: object, *, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    value = re.sub(r"\s+", " ", _CONTROL_CHARS.sub(" ", value)).strip()
    if not value:
        return None
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def _local_to_utc_iso(value: object, tz_name: str) -> str | None:
    """Drafts carry a local wall-clock time (no offset). An explicit offset,
    if a model adds one anyway, is honoured instead of guessed away."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
        if _DATE_ONLY.match(text):
            # A bare date means "by the end of that day", same as the fallback.
            parsed = parsed.replace(hour=23, minute=59)
        iso = (
            timeutil.to_iso(parsed)
            if parsed.tzinfo is not None
            else timeutil.local_to_utc_iso(parsed, tz_name)
        )
        # Same window the task API enforces; anything outside is a misread.
        return iso if DUE_YEAR_MIN <= int(iso[:4]) <= DUE_YEAR_MAX else None
    except (ValueError, OverflowError):
        # OverflowError: year 9999 / year 1 plus an offset falls off the
        # datetime range — drop that one date, not the whole batch.
        return None


def sanitize_draft(raw: dict, *, tz_name: str, flags: dict) -> dict | None:
    title = _clean_text(raw.get("title"), limit=TITLE_MAX_LENGTH)
    if title is None:
        return None
    tag = raw.get("tag")
    estimate = raw.get("estimate_hours")
    valid_estimate = (
        isinstance(estimate, int | float)
        and not isinstance(estimate, bool)
        and MIN_ESTIMATE_HOURS <= estimate <= MAX_ESTIMATE_HOURS
    )
    return {
        "title": title,
        "tag": tag if tag in TAGS else "personal",
        "due_at": _local_to_utc_iso(raw.get("due_at"), tz_name),
        "estimate_hours": float(estimate) if valid_estimate and flags.get("estimates") else None,
        "notes": _clean_text(raw.get("notes"), limit=_NOTES_MAX_CHARS),
    }


def _dedupe(drafts: list[dict]) -> list[dict]:
    seen: set[tuple[str, str | None]] = set()
    unique = []
    for draft in drafts:
        key = (draft["title"].casefold(), draft["due_at"])
        if key not in seen:
            seen.add(key)
            unique.append(draft)
    return unique


def enforce_transcribe_limit(user_id: int) -> None:
    if not transcribe_limiter.allow(user_id):
        raise ApiError("rate_limited", "Too many recordings — wait a minute and retry", 429)


def enforce_rate_limit(user_id: int) -> None:
    """Called by the route BEFORE any expensive work (PDF parsing, uploads),
    so a flood of bad or oversized requests still counts against the budget."""
    if not rate_limiter.allow(user_id):
        raise ApiError("rate_limited", "Too many capture requests — wait a minute and retry", 429)


# Where a dictated run of words is cut into separate tasks. Deliberately narrow: only
# "and then" / "after that" / ", then" or a real sentence end. Words like "next",
# "then", "also" occur INSIDE ordinary tasks ("by next Friday", "read the next
# chapter"), so they are never separators on their own.
_TASK_JOINERS = re.compile(r"\s+(?:and then|after that)\s+|,\s*then\s+", re.IGNORECASE)
_SENTENCE_END = re.compile(r"(?<=[.!?;])\s+")
_ABBREVIATIONS = frozenset(
    "mr mrs ms dr prof sr jr st vs etc e.g i.e a.m p.m am pm no fig ch sec approx".split()
)
# A sentence that begins "Also call mom" / "Then rest" / "And email Sam" (never "next").
_DICTATION_LEAD = re.compile(r"^(?:and then|and also|and|also|then|after that)\s+", re.IGNORECASE)
_DICTATION_PREFIX = re.compile(
    r"^(?:please\s+)?(?:remind me to|remind me about|"
    # "add ...", "add a task to ...", "create a new reminder called ..."
    r"(?:add|create)(?: (?:a|an))?(?: new)?(?: (?:task|reminder))?(?: to| for| called| named)?|"
    r"i (?:need|have|got) to|i must|don'?t forget to|make (?:a )?note to)\s+",
    re.IGNORECASE,
)
# Speech recognisers write acronyms in lower case; these are the ones students say.
_ACRONYMS = re.compile(
    r"\b(dbms|os|cn|dsa|ai|ml|sql|cpu|api|ui|ux|ece|cse|eee|hod|hr|pdf|ppt|cgpa|gpa|ia|cat|nptel)\b",
    re.IGNORECASE,
)


def _sentences(text: str) -> list[str]:
    """Split at sentence ends, but not after an abbreviation ("Dr. Rao", "5 p.m.
    tomorrow") and not before a lower-case word (a recogniser that adds full stops
    still starts real sentences with a capital)."""
    pieces = _SENTENCE_END.split(text)
    merged: list[str] = []
    for piece in pieces:
        if merged:
            previous = merged[-1]
            last_word = (
                previous.rstrip(".!?;").split()[-1].lower().rstrip(".") if previous.split() else ""
            )
            hard_break = previous.endswith(";") or (previous[-1:] in ".!?" and piece[:1].isupper())
            if not hard_break or last_word in _ABBREVIATIONS:
                merged[-1] = f"{previous} {piece}"
                continue
        merged.append(piece)
    return merged


def normalize_dictation(text: str) -> str:
    """Spoken text arrives as one unpunctuated run: "remind me to submit the lab
    record by friday five pm and then email the professor". Split it into one task
    per line, drop the "remind me to" lead-in, fix acronym case, and capitalise — so
    the same extraction used for typed text gives sensible titles."""
    lines = []
    for sentence in _sentences(text.strip()):
        for chunk in _TASK_JOINERS.split(sentence):
            chunk = _DICTATION_LEAD.sub("", chunk.strip())
            chunk = _DICTATION_PREFIX.sub("", chunk).strip(" ,.;!?")
            if chunk:
                chunk = _ACRONYMS.sub(lambda m: m[1].upper(), chunk)
                lines.append(chunk[0].upper() + chunk[1:])
    return "\n".join(lines)


def preview(
    *,
    user_id: int,
    text: object,
    tz_name: str,
    flags: dict,
    config: Mapping[str, Any],
    voice: bool = False,
) -> dict:
    """Never touches the database. Returns the drafts plus which producer
    made them, so the UI can say when it fell back to the simple extractor."""
    text = require_str(text, "text").strip()
    if not text:
        raise ApiError("validation", "Paste some text or upload a PDF first", 422)
    if len(text) > CAPTURE_TEXT_MAX_CHARS:
        raise ApiError(
            "validation", f"Text must be at most {CAPTURE_TEXT_MAX_CHARS} characters", 422
        )
    if voice:
        text = normalize_dictation(text)
        if not text:
            raise ApiError("validation", "I didn't catch any words — try again", 422)
    now_local = timeutil.utcnow().astimezone(ZoneInfo(tz_name))
    source, fallback_reason = "gemini", None
    try:
        raw_drafts = gemini_client.generate_task_drafts(
            text,
            now_local_iso=now_local.strftime("%Y-%m-%dT%H:%M:%S"),
            tz_name=tz_name,
            config=config,
        )
    except gemini_client.GeminiUnavailable as exc:
        logger.warning("capture_gemini_unavailable reason=%s", exc)
        source, fallback_reason = "fallback", "ai_unavailable"
        raw_drafts = fallback_extractor.extract_drafts(text, now_local=now_local, tz_name=tz_name)

    # Cap before sanitising: a model (or a prompt-injected one) can return far
    # more rows than we will ever show.
    cleaned = (
        sanitize_draft(raw, tz_name=tz_name, flags=flags)
        for raw in raw_drafts[: CAPTURE_MAX_DRAFTS * 2]
    )
    drafts = _dedupe([d for d in cleaned if d is not None])[:CAPTURE_MAX_DRAFTS]
    result = {"source": source, "tasks": drafts}
    if fallback_reason:
        result["fallback_reason"] = fallback_reason
    return result


def confirm(conn: sqlite3.Connection, *, user_id: int, tasks: object, flags: dict) -> list[dict]:
    """Saves exactly the rows the user ticked. All rows are validated before
    the first INSERT, so one bad row can't leave a half-saved batch."""
    if not isinstance(tasks, list) or not tasks:
        raise ApiError("validation", "Select at least one task to save", 422)
    if len(tasks) > CAPTURE_MAX_DRAFTS:
        raise ApiError("validation", f"At most {CAPTURE_MAX_DRAFTS} tasks per save", 422)

    validated = []
    for index, item in enumerate(tasks, start=1):
        if not isinstance(item, dict):
            raise ApiError("validation", f"Task {index}: must be an object", 422)
        try:
            validated.append(
                task_service.validate_new_task(
                    title=item.get("title"),
                    notes=item.get("notes"),
                    tag=item.get("tag"),
                    due_at=item.get("due_at"),
                    estimate_hours=item.get("estimate_hours"),
                    flags=flags,
                )
            )
        except ApiError as exc:
            raise ApiError(exc.code, f"Task {index}: {exc.message}", exc.status) from exc

    return [
        task_service.create_task(conn, user_id=user_id, flags=flags, **fields)
        for fields in validated
    ]
