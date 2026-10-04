"""Rule-based task extractor: the no-AI path of smart capture (ADR 0006).

One task per line; dates and times are read with an explicit grammar rather
than a free-text date library. The library this used to rely on silently
invented dates from ordinary text ("Project 2 by Friday" -> a past Friday,
"Quiz 2 on 10/12" -> the year 2112, "Monday 9am" -> Friday). The rule here is
the opposite: recognise a small set of unambiguous patterns, validate every
result, and when in doubt return NO date — the review screen then shows
"no deadline found" and a person decides, instead of a wrong day being saved.

Recognised: ISO (2026-10-15 [10:00]), D/M[/Y] (day first, as in India), month
names (5th Oct, Oct 5, 5 October 2026), today / tonight / tomorrow / day after
tomorrow, in N days|weeks, weekdays (Friday, next Friday), "the 1st", Hinglish
kal / aaj / parso (and कल / आज / परसों), EOD, clock times (5pm, 17:00, noon) and
a time-zone word after a time (IST, EST, UTC ...)."""

import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.constants import CAPTURE_MAX_DRAFTS

MAX_LINES_SCANNED = 300
_MIN_TITLE_CHARS = 3
END_OF_DAY = (23, 59)
EOD_TIME = (18, 0)
# How far from "now" an explicit year may be before we distrust it as a
# misread number (e.g. 10/12 read as year 2112, "2/3" read as March 2027).
_YEAR_WINDOW = (-1, 3)
_RECENT_PAST_DAYS = 60

_BULLET = re.compile(r"^\s*(?:[-*•–]|\d{1,2}[.)])\s+")
_LEAD_LABEL = re.compile(r"^(?:todo|to do|task|reminder|action)\s*[:\-]\s*", re.I)
_CONNECTOR_WORDS = frozenset(
    "by due on before until till at for next this coming from tak deadline".split()
)
_EMPTY_BRACKETS = re.compile(r"[(\[]\s*[)\]]")
_ESTIMATE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(hours?|hrs?|h|minutes?|mins?)\b", re.I)
# Chat/email exports prefix every line with its own send time:
#   [04/10/2026, 10:15:32] Prof: ...      4/10/26, 10:15 am - Prof: ...
# That is when the message was SENT, never the deadline.
_CHAT_PREFIX = re.compile(
    r"^\s*\[?\s*\d{1,2}[/.]\d{1,2}[/.]\d{2,4},?\s+\d{1,2}:\d{2}(?::\d{2})?\s*"
    r"(?:[ap]\.?m\.?)?\s*\]?\s*[-–]?\s*",
    re.I,
)
MAX_LINE_CHARS = 400  # a task line is a sentence; bounds every regex below

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}  # fmt: skip
_WEEKDAYS = {
    "monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "tues": 1, "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thur": 3, "thurs": 3, "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5, "sunday": 6, "sun": 6,
}  # fmt: skip
# Fixed UTC offsets (hours) for the zone words people actually write.
_ZONE_OFFSETS = {
    "IST": 5.5, "UTC": 0, "GMT": 0, "EST": -5, "EDT": -4, "CST": -6, "CDT": -5,
    "MST": -7, "MDT": -6, "PST": -8, "PDT": -7, "CET": 1, "CEST": 2, "BST": 1, "SGT": 8,
}  # fmt: skip

_MONTH_RE = "|".join(sorted(_MONTHS, key=len, reverse=True))
_WEEKDAY_RE = "|".join(sorted(_WEEKDAYS, key=len, reverse=True))
_CUE_BEFORE = re.compile(
    r"(?:by|due|on|before|until|till|deadline|submit)\W+(?:\w+\W+){0,2}$", re.I
)
_TIME_CUE_BEFORE = re.compile(r"(?:\bat|@|\bby|\bbefore|\buntil|\btill|\bfrom|\baround)\s*$", re.I)
_WORD = r"[\w\u0900-\u097F'’]"  # \b is unreliable around Devanagari combining marks

_ISO = re.compile(
    r"(?<![\d-])(\d{4})-(\d{2})-(\d{2})"
    r"(?:[T ](\d{2}):(\d{2})(?::\d{2})?(?:\s?(Z|[+-]\d{2}:?\d{2}))?)?(?![\d-])"
)
_NUMERIC = re.compile(r"(?<![\d/.:-])(\d{1,2})[/.](\d{1,2})(?:[/.](\d{4}|\d{2}))?(?![\d/:])")
_DAY_MONTH = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MONTH_RE})\b\.?(?:,?\s+(\d{{4}}))?", re.I
)
_MONTH_DAY = re.compile(
    rf"\b({_MONTH_RE})\b\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?!:)(?:,?\s+(\d{{4}}))?", re.I
)
# A bare ordinal is only a date after a deadline word ("by the 5th"); on its own
# it is "10th class", "2nd semester", "1st year".
_ORDINAL = re.compile(
    r"(?:by|on|before|until|till|due)\s+(?:the\s+)?(\d{1,2})(?:st|nd|rd|th)\b", re.I
)
_RELATIVE = re.compile(
    rf"(?<!{_WORD})(?:day after tomorrow|tomorrow|tonight|today|aaj|parso|kal(?!\s+(?:ki|ke|ka)\b)"
    rf"|कल|आज|परसों)(?!{_WORD})",
    re.I,
)
_IN_N = re.compile(r"\bin\s+(\d{1,2})\s+(day|days|week|weeks)\b", re.I)
_WEEKDAY = re.compile(rf"\b(?:(next|this|coming)\s+)?({_WEEKDAY_RE})\b", re.I)
_EOD = re.compile(r"\b(?:eod|cob|end of (?:the )?day)\b", re.I)
_ZONES = "|".join(_ZONE_OFFSETS)
_AMPM = r"(?:[ap]\.?m\.?)"
# 5pm  5:30pm  5.30pm  5:30 p.m.  17:00  17h30  noon — and ranges ("5pm-6pm", "5-6pm"),
# where the START is the time that matters.
_CLOCK = re.compile(
    rf"(?<![\d:.])(?:(\d{{1,2}})(?:[:.](\d{{2}}))?\s*({_AMPM})(?![a-z])"
    rf"|(\d{{1,2}}):(\d{{2}})(?![\d:])"
    rf"|(\d{{1,2}})h(\d{{2}})\b"
    rf"|\b(noon|midnight)\b)"
    rf"(?:\s*(?:-|–|to)\s*\d{{1,2}}(?:[:.]\d{{2}})?\s*(?:{_AMPM})?)?"
    rf"(?:\s*({_ZONES})\b)?",
    re.I,
)
_RANGE_START = re.compile(
    rf"(?<![\d:.])(\d{{1,2}})(?:[:.](\d{{2}}))?\s*(?:-|–|to)\s*\d{{1,2}}(?:[:.]\d{{2}})?\s*({_AMPM})",
    re.I,
)

_TAG_KEYWORDS = {
    "study": (
        "assignment",
        "exam",
        "quiz",
        "lab",
        "lecture",
        "homework",
        "syllabus",
        "chapter",
        "revise",
        "revision",
        "study",
        "course",
        "viva",
        "thesis",
        "semester",
        "tutorial",
    ),
    "work": (
        "meeting",
        "client",
        "report",
        "standup",
        "deploy",
        "review",
        "invoice",
        "sprint",
        "presentation",
        "proposal",
        "stakeholder",
        "deck",
    ),
}


_NUM_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20,
    "thirty": 30, "forty five": 45, "forty-five": 45, "sixty": 60, "ninety": 90,
}  # fmt: skip
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50}
_UNITS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
          "eight": 8, "nine": 9}  # fmt: skip
for _t, _tv in _TENS.items():
    for _u, _uv in _UNITS.items():
        _NUM_WORDS[f"{_t} {_u}"] = _NUM_WORDS[f"{_t}-{_u}"] = _tv + _uv
_NUM_WORDS.update({"forty": 40, "fifty": 50})
_NUM_WORD_RE = "|".join(sorted(_NUM_WORDS, key=len, reverse=True))
# "in an hour" / "in two hours" is WHEN (relative time), not how long it takes.
_NOT_AFTER_IN = r"(?<!\bin )"
_SPOKEN_DURATIONS = (
    (re.compile(rf"{_NOT_AFTER_IN}\bquarter\s+of\s+an\s+hour\b", re.I), "15 minutes"),
    (re.compile(rf"{_NOT_AFTER_IN}\b(?:an|one)\s+hour\s+and\s+a\s+half\b", re.I), "1.5 hours"),
    (re.compile(rf"{_NOT_AFTER_IN}\bhalf\s+an?\s+hour\b", re.I), "30 minutes"),
    (re.compile(rf"{_NOT_AFTER_IN}\ban?\s+hour\b", re.I), "1 hour"),
)
_SPOKEN_NUMBER_UNIT = re.compile(
    rf"{_NOT_AFTER_IN}\b({_NUM_WORD_RE})\s+(hours?|hrs?|minutes?|mins?)\b", re.I
)
_SPOKEN_CLOCK = re.compile(
    rf"\b({_NUM_WORD_RE})(?:\s+(fifteen|thirty|forty[ -]five))?\s*([ap])\.?\s?m\.?(?![a-z])", re.I
)


def spoken_durations_to_digits(line: str) -> str:
    """ "two hours" / "half an hour" -> "2 hours" / "30 minutes", so a dictated
    estimate is read the same way a typed one is."""
    for pattern, replacement in _SPOKEN_DURATIONS:
        line = pattern.sub(replacement, line)
    line = _SPOKEN_NUMBER_UNIT.sub(lambda m: f"{_NUM_WORDS[m[1].lower()]} {m[2]}", line)
    return _SPOKEN_CLOCK.sub(_spoken_clock, line)


def _spoken_clock(m: re.Match) -> str:
    """ "five thirty pm" -> "5:30 pm" (only 1-12 are clock hours)."""
    hour = _NUM_WORDS[m[1].lower()]
    if not 1 <= hour <= 12:
        return m[0]
    minutes = _NUM_WORDS[m[2].lower().replace(" ", "-")] if m[2] else 0
    return f"{hour}:{minutes:02d} {m[3].lower()}m" if minutes else f"{hour} {m[3].lower()}m"


def _guess_tag(line: str) -> str:
    lowered = line.lower()
    for tag, words in _TAG_KEYWORDS.items():
        if any(re.search(rf"\b{re.escape(w)}", lowered) for w in words):
            return tag
    return "personal"


def _ampm(token: str) -> str:
    return "pm" if token.lower().startswith("p") else "am"


def _to_24h(hour: int, minute: int, meridiem: str | None) -> tuple[int, int] | None:
    if minute >= 60:
        return None
    if meridiem is None:
        return (hour, minute) if hour < 24 else None
    if not 1 <= hour <= 12:
        return None
    hour %= 12
    return (hour + 12 if meridiem == "pm" else hour), minute


def _clock_from(match: re.Match) -> tuple[int, int] | None:
    if match.group(8):
        return (12, 0) if match.group(8).lower() == "noon" else (0, 0)
    if match.group(3):
        hour, minute, meridiem = (
            int(match.group(1)),
            int(match.group(2) or 0),
            _ampm(match.group(3)),
        )
        # "5-6pm": no am/pm on the start, so it shares the end's.
        return _to_24h(hour, minute, meridiem)
    if match.group(4):
        return _to_24h(int(match.group(4)), int(match.group(5)), None)
    return _to_24h(int(match.group(6)), int(match.group(7)), None)


def _safe_date(year: int, month: int, day: int, today: datetime) -> datetime | None:
    """A real calendar date within a sane window around today, else None."""
    lo, hi = today.year + _YEAR_WINDOW[0], today.year + _YEAR_WINDOW[1]
    if not lo <= year <= hi:
        return None
    try:
        return datetime(year, month, day)
    except ValueError:
        return None


def _yearless(month: int, day: int, today: datetime) -> datetime | None:
    """Month/day with no year: this year, unless it passed long ago (then next
    year). A date only a few weeks past stays in THIS year and shows as overdue
    — pushing "due 3 Oct" said on 4 Oct to next October would be the worse lie."""
    this_year = _safe_date(today.year, month, day, today)
    if this_year is None:
        return None
    if (today - this_year).days > _RECENT_PAST_DAYS:
        return _safe_date(today.year + 1, month, day, today)
    return this_year


def _next_weekday(target: int, today: datetime, *, push_today: bool) -> datetime:
    days = (target - today.weekday()) % 7
    if days == 0 and push_today:
        days = 7
    return today + timedelta(days=days)


# Rank decides which date wins when a line has several. Explicit calendar dates
# beat relative words, so "Monday 12 Oct" is 12 Oct (not the coming Monday) and
# "by EOD tomorrow" is tomorrow; within a rank the later one in the text wins.
_RANK_EXPLICIT, _RANK_RELATIVE = 2, 1


def _date_matches(line: str, today: datetime) -> list[tuple[int, int, datetime, int]]:
    """(start, end, date at midnight, rank) for every date phrase found."""
    found: list[tuple[int, int, datetime, int]] = []
    taken: list[tuple[int, int]] = []

    def free(span: tuple[int, int]) -> bool:
        return not any(span[0] < e and s < span[1] for s, e in taken)

    def add(m: re.Match, date: datetime | None, rank: int) -> None:
        if date is not None and free(m.span()):
            found.append((m.start(), m.end(), date, rank))
            taken.append(m.span())

    for m in _ISO.finditer(line):
        add(m, _safe_date(int(m[1]), int(m[2]), int(m[3]), today), _RANK_EXPLICIT)
    for m in _NUMERIC.finditer(line):
        day, month = int(m[1]), int(m[2])
        if m[3]:
            year = int(m[3]) + (2000 if len(m[3]) == 2 else 0)
            add(m, _safe_date(year, month, day, today), _RANK_EXPLICIT)
        elif "/" in m[0] and _CUE_BEFORE.search(line[: m.start()]):
            # "Room 3/12" and "2/3 people" are not dates; "due 3/12" is.
            add(m, _yearless(month, day, today), _RANK_EXPLICIT)

    day_month = [(m, _MONTHS[m[2].lower()]) for m in _DAY_MONTH.finditer(line)]
    month_day = [(m, _MONTHS[m[1].lower()]) for m in _MONTH_DAY.finditer(line)]
    ambiguous = [
        (a, b)
        for a, _ in day_month
        for b, _ in month_day
        if a.start() < b.end() and b.start() < a.end()
    ]
    clashing = {id(x) for pair in ambiguous for x in pair}  # "Project 3 Nov 20": which is the day?
    for m, month in day_month:
        if id(m) in clashing:
            continue
        date = (
            _safe_date(int(m[3]), month, int(m[1]), today)
            if m[3]
            else _yearless(month, int(m[1]), today)
        )
        add(m, date, _RANK_EXPLICIT)
    for m, month in month_day:
        if id(m) in clashing:
            continue
        date = (
            _safe_date(int(m[3]), month, int(m[2]), today)
            if m[3]
            else _yearless(month, int(m[2]), today)
        )
        add(m, date, _RANK_EXPLICIT)
    for m in _ORDINAL.finditer(line):
        day = int(m[1])
        this_month = _safe_date(today.year, today.month, day, today)
        if this_month is not None and this_month < today:
            this_month = _safe_date(
                today.year + (today.month == 12), today.month % 12 + 1, day, today
            )
        add(m, this_month, _RANK_EXPLICIT)
    for m in _IN_N.finditer(line):
        n = int(m[1]) * (7 if m[2].lower().startswith("week") else 1)
        add(m, today + timedelta(days=n), _RANK_RELATIVE)
    for m in _RELATIVE.finditer(line):
        word = m[0].lower()
        offset = {"day after tomorrow": 2, "parso": 2, "परसों": 2}.get(word)
        if offset is None:
            offset = 1 if word in ("tomorrow", "kal", "कल") else 0
        add(m, today + timedelta(days=offset), _RANK_RELATIVE)
    for m in _WEEKDAY.finditer(line):
        push = bool(m[1] and m[1].lower() == "next")
        add(m, _next_weekday(_WEEKDAYS[m[2].lower()], today, push_today=push), _RANK_RELATIVE)
    return found


class _Span:
    """Stand-in for a regex match where only .span()/.group() are used."""

    def __init__(self, span: tuple[int, int]) -> None:
        self._span = span

    def span(self) -> tuple[int, int]:
        return self._span

    def group(self, _n: int) -> None:
        return None


def _pick_clock(
    line: str, date_end: int | None, date_spans: list[tuple[int, int]]
) -> tuple[re.Match | _Span | None, tuple[int, int] | None]:
    """The clock time that belongs to the deadline: one after a cue word
    ("at 5pm"), carrying am/pm, or sitting right after the date. A bare H:MM
    elsewhere ("John 3:16", "video 3:45") is just a number."""
    chosen = None
    rng = _RANGE_START.search(line)
    if rng and not any(a < rng.end() and rng.start() < b for a, b in date_spans):
        # "5-6pm": the start inherits the end's am/pm.
        clock = _to_24h(int(rng[1]), int(rng[2] or 0), _ampm(rng[3]))
        if clock is not None:
            return _Span(rng.span()), clock
    for m in _CLOCK.finditer(line):
        if any(s < m.end() and m.start() < e for s, e in date_spans):
            continue  # that time belongs to an ISO timestamp already read as a date
        clock = _clock_from(m)
        if clock is None:
            continue
        bare = m.group(4) is not None or m.group(6) is not None  # no am/pm word
        if bare:
            near_date = any(0 <= m.start() - e <= 3 or 0 <= a - m.end() <= 3 for a, e in date_spans)
            if not (_TIME_CUE_BEFORE.search(line[: m.start()]) or near_date):
                continue
        if date_end is not None and m.start() >= date_end - 1:
            return m, clock  # nearest following the date wins
        chosen = chosen or (m, clock)
    return chosen if chosen else (None, None)


def _find_due(line: str, now_local: datetime, tz_name: str) -> tuple[str | None, str]:
    """Returns (local naive ISO due, line with the date/time phrases removed).
    No recognisable, plausible date -> (None, line)."""
    now = now_local.replace(tzinfo=None)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    line = _CHAT_PREFIX.sub("", line, count=1)

    dates = _date_matches(line, today)
    eod = next(iter(_EOD.finditer(line)), None)
    chosen = max(dates, key=lambda d: (d[3], d[1])) if dates else None
    clock_match, clock = _pick_clock(
        line, chosen[1] if chosen else None, [(d[0], d[1]) for d in dates]
    )
    iso_time = None
    if chosen is not None:
        iso = _ISO.fullmatch(line[chosen[0] : chosen[1]])
        if iso and iso[4]:
            iso_time = (int(iso[4]), int(iso[5]), iso[6])
            clock = _to_24h(iso_time[0], iso_time[1], None)
    if chosen is None and clock is None and eod is None:
        return None, line

    spans: list[tuple[int, int]] = []
    if chosen is not None:
        start, end, date, _rank = chosen
        tak = re.match(r"\s+tak\b", line[end:])  # Hinglish "kal tak" = "by tomorrow"
        spans.append((start, end + (tak.end() if tak else 0)))
        # A weekday/relative word that merely describes the same date ("Monday 12 Oct")
        # leaves the title once the explicit date has been taken.
        if chosen[3] == _RANK_EXPLICIT:
            spans.extend((d[0], d[1]) for d in dates if d[3] == _RANK_RELATIVE)
    else:
        # A bare time or "EOD": today if still ahead, else tomorrow.
        date = today
        if clock is not None and today.replace(hour=clock[0], minute=clock[1]) <= now:
            date = today + timedelta(days=1)
        if clock is None:
            date = today

    hour, minute = clock if clock is not None else (EOD_TIME if eod else END_OF_DAY)
    due = date.replace(hour=hour, minute=minute)
    if eod is not None:
        spans.append(eod.span())

    if iso_time is not None and iso_time[2]:
        # "2026-10-14T09:00+05:30" / "...Z": an explicit offset, honoured.
        raw = iso_time[2].upper()
        if raw == "Z":
            offset = timezone.utc
        else:
            sign = -1 if raw[0] == "-" else 1
            digits = raw[1:].replace(":", "")
            offset = timezone(sign * timedelta(hours=int(digits[:2]), minutes=int(digits[2:])))
        due = due.replace(tzinfo=offset).astimezone(ZoneInfo(tz_name)).replace(tzinfo=None)

    if clock_match is not None:
        spans.append(clock_match.span())
        zone = (clock_match.group(9) or "").upper()
        if zone:
            # "5pm EST" is five o'clock THERE: convert to the user's own zone.
            offset = timezone(timedelta(hours=_ZONE_OFFSETS[zone]))
            due = due.replace(tzinfo=offset).astimezone(ZoneInfo(tz_name)).replace(tzinfo=None)

    remaining = line
    for s, e in sorted(set(spans), reverse=True):
        remaining = remaining[:s] + " " + remaining[e:]
    return due.strftime("%Y-%m-%dT%H:%M:%S"), remaining


def _find_estimate(line: str) -> float | None:
    match = _ESTIMATE.search(line)
    if not match:
        return None
    value = float(match.group(1))
    return round(value / 60, 2) if match.group(2).lower().startswith("m") else value


def _strip_connectors(tokens: list[str], *, trailing: bool) -> list[str]:
    """Drop leftover "by"/"due"/"on" words at one edge, one token at a time (a
    regex loop here was quadratic on long runs of connector words)."""
    while tokens and tokens[-1 if trailing else 0].strip(",;:–-.").lower() in _CONNECTOR_WORDS:
        tokens.pop(-1 if trailing else 0)
    return tokens


def _clean_title(text: str) -> str:
    text = _BULLET.sub("", text)
    text = _LEAD_LABEL.sub("", text)
    tokens = text.replace("\u00a0", " ").split()
    tokens = _strip_connectors(_strip_connectors(tokens, trailing=True), trailing=False)
    cleaned = " ".join(tokens)
    cleaned = re.sub(r"\s+([,;:.])", r"\1", cleaned)
    return cleaned.strip(" \t,;:–-.")


def extract_drafts(text: str, *, now_local: datetime, tz_name: str) -> list[dict]:
    ZoneInfo(tz_name)  # fail fast on a bad tz rather than inside dateparser
    drafts: list[dict] = []
    for line in text.splitlines()[:MAX_LINES_SCANNED]:
        stripped = spoken_durations_to_digits(line.strip()[:MAX_LINE_CHARS])
        if len(stripped) < _MIN_TITLE_CHARS or stripped.endswith(":"):
            continue
        # Durations ("3 hours", "30 min") are removed first: dateparser reads
        # them as relative dates and would eat them out of the title.
        without_estimate = _EMPTY_BRACKETS.sub(" ", _ESTIMATE.sub(" ", stripped))
        due, without_date = _find_due(without_estimate, now_local, tz_name)
        title = _clean_title(without_date)
        if len(title) < _MIN_TITLE_CHARS:
            continue
        drafts.append(
            {
                "title": title,
                "tag": _guess_tag(stripped),
                "due_at": due,
                "estimate_hours": _find_estimate(stripped),
                "notes": None,
            }
        )
        if len(drafts) >= CAPTURE_MAX_DRAFTS:
            break
    return drafts
