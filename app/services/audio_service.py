"""Rules for a recorded clip sent to /api/voice/transcribe: which formats are
accepted, what MIME type Gemini is told, and a cheap sanity check that the
bytes are plausibly audio and not an HTML error page or text pasted into the
wrong field. The upload is never stored; this only decides whether to forward it."""

from app.errors import ApiError

MAX_AUDIO_BYTES = 2 * 1024 * 1024  # roughly 1-2 minutes of speech
MIN_AUDIO_BYTES = 200

# What browsers send (MediaRecorder: webm/opus on Chrome and Firefox, ogg/opus
# on some Firefox builds, mp4/aac on Safari) -> the MIME type forwarded to
# Gemini. Gemini documents wav, mp3, aiff, aac, ogg and flac; webm and mp4 are
# forwarded as they are because that is what browsers record, and Gemini sniffs
# the container. Aliases are folded onto the canonical name.
_MIME_ALIASES: dict[str, str] = {
    "audio/webm": "audio/webm",
    "audio/ogg": "audio/ogg",
    "audio/opus": "audio/ogg",
    "audio/mp4": "audio/mp4",
    "audio/m4a": "audio/mp4",
    "audio/x-m4a": "audio/mp4",
    "audio/mpeg": "audio/mp3",
    "audio/mp3": "audio/mp3",
    "audio/wav": "audio/wav",
    "audio/x-wav": "audio/wav",
    "audio/wave": "audio/wav",
    "audio/vnd.wave": "audio/wav",
    "audio/aac": "audio/aac",
    "audio/aiff": "audio/aiff",
    "audio/x-aiff": "audio/aiff",
    "audio/flac": "audio/flac",
    "audio/x-flac": "audio/flac",
}

_SNIFF_BYTES = 512


def normalize_mime(raw: str | None) -> str | None:
    """ "audio/WebM; codecs=opus" -> "audio/webm"; None when not an accepted type."""
    base = (raw or "").split(";")[0].strip().lower()
    return _MIME_ALIASES.get(base)


def _looks_like_text(head: bytes) -> bool:
    """True for an HTML/JSON/plain-text payload. Real audio containers start with
    binary magic (RIFF, OggS, fLaC, EBML, ftyp, ID3...) and contain control bytes
    within the first few hundred bytes."""
    if head.lstrip()[:1] == b"<":
        return True
    try:
        decoded = head.decode("utf-8")
    except UnicodeDecodeError:
        # A multibyte character cut at the sniff boundary is still text; any
        # other decode failure means binary data.
        try:
            decoded = head[:-3].decode("utf-8")
        except UnicodeDecodeError:
            return False
    return all(ch in "\t\n\r" or ch >= " " and ch != "\x7f" for ch in decoded)


def validate_clip(audio: bytes) -> None:
    """Raises ApiError for a clip that is too long, too short or not audio."""
    if len(audio) > MAX_AUDIO_BYTES:
        raise ApiError("validation", "That recording is too long — keep it under a minute", 413)
    if len(audio) < MIN_AUDIO_BYTES:
        raise ApiError("validation", "I didn't hear anything — try again", 422)
    if _looks_like_text(audio[:_SNIFF_BYTES]):
        raise ApiError("validation", "That file doesn't look like audio", 415)
