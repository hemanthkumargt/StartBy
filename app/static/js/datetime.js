// Every timestamp from the API is a naive UTC string ("2026-10-03T11:30:00",
// no offset) — PRD invariant I9. JS treats an offset-less string as LOCAL
// time, so every parse here appends "Z" first to get the right instant.
// Converting a <input type="datetime-local"> value back to UTC relies on
// the opposite fact: that string has no offset either, so `new Date(...)`
// correctly reads it as the browser's local time, and toISOString() gives
// back UTC for the API.
//
// Read-only display (formatDateTime) honors the user's saved Settings
// timezone via Intl's timeZone option. Editing (toLocalInputValue /
// fromLocalInputValue) cannot: a native <input type="datetime-local">
// always reads and writes the browser's own local time with no way to
// point it at a different IANA zone, so both of those stay tied to the
// browser's timezone to round-trip correctly with what the input itself
// does.

// The Settings timezone, or undefined when it is absent or this browser's ICU
// does not know it (Python's tz database can be newer than an old browser's:
// Intl would throw RangeError and take every card and form down with it).
let cachedZone = { raw: null, ok: undefined };
function userTimezone() {
  const meta = document.querySelector('meta[name="user-timezone"]');
  const raw = meta && meta.content ? meta.content : undefined;
  if (!raw) return undefined;
  if (cachedZone.raw !== raw) {
    let ok;
    try {
      new Intl.DateTimeFormat("en-CA", { timeZone: raw });
      ok = raw;
    } catch {
      ok = undefined;
    }
    cachedZone = { raw, ok };
  }
  return cachedZone.ok;
}

const RELATIVE_UNITS = [
  ["year", 31536000],
  ["month", 2592000],
  ["week", 604800],
  ["day", 86400],
  ["hour", 3600],
  ["minute", 60],
];

export function parseUtc(value) {
  if (!value) return null;
  const iso = value.endsWith("Z") || /[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`;
  return new Date(iso);
}

// Date-time inputs are read and written in the user's Settings timezone — the
// same zone formatDateTime shows and the emails/calendar use — not the
// browser's. Mixing the two made the edit form disagree with the card for
// anyone whose laptop clock zone differs from their saved zone.
function wallClockParts(ms, tz) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: tz,
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).formatToParts(new Date(ms));
  const get = (type) => Number(parts.find((p) => p.type === type).value);
  return { y: get("year"), m: get("month"), d: get("day"), h: get("hour"), mi: get("minute") };
}

// Offset (ms) of `tz` from UTC at the instant `ms`.
function zoneOffsetMs(ms, tz) {
  const p = wallClockParts(ms, tz);
  return Date.UTC(p.y, p.m - 1, p.d, p.h, p.mi) - Math.floor(ms / 60000) * 60000;
}

export function toLocalInputValue(utcIso) {
  const d = parseUtc(utcIso);
  if (!d) return "";
  const pad = (n) => String(n).padStart(2, "0");
  const tz = userTimezone();
  if (!tz) {
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }
  const p = wallClockParts(d.getTime(), tz);
  return `${p.y}-${pad(p.m)}-${pad(p.d)}T${pad(p.h)}:${pad(p.mi)}`;
}

export const MIN_YEAR = 2000;
export const MAX_YEAR = 2100;

export class DateInputError extends Error {}

// A typed value that is present but unusable ("26" -> year 0026, "20266", a
// half-cleared field) must be reported, not turned into null — null means
// "no deadline", which would silently create the task without one or erase an
// existing deadline on edit.
export function fromLocalInputValue(localValue) {
  if (!localValue) return null;
  const m = /^(\d{4,6})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(localValue);
  const year = m ? Number(m[1]) : NaN;
  if (!m || year < MIN_YEAR || year > MAX_YEAR) {
    throw new DateInputError(
      `Please enter a valid deadline with a year between ${MIN_YEAR} and ${MAX_YEAR}.`
    );
  }
  const tz = userTimezone();
  const wall = new Date(0);
  wall.setUTCFullYear(year, Number(m[2]) - 1, Number(m[3]));
  wall.setUTCHours(Number(m[4]), Number(m[5]), 0, 0);
  const asUtc = wall.getTime();
  if (!tz) {
    // No saved zone to apply: interpret the wall time in the browser's own.
    const local = new Date(year, Number(m[2]) - 1, Number(m[3]), Number(m[4]), Number(m[5]));
    return local.toISOString();
  }
  // The wall time is in `tz`: subtract that zone's offset. Re-check once,
  // because the offset at the guessed instant can differ across a DST change.
  const first = zoneOffsetMs(asUtc, tz);
  let instant = asUtc - first;
  const second = zoneOffsetMs(instant, tz);
  if (second !== first) instant = asUtc - second;
  return new Date(instant).toISOString();
}

export function formatDateTime(utcIso) {
  const d = parseUtc(utcIso);
  if (!d) return "";
  return d.toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: userTimezone(),
  });
}

export function relativeTime(utcIso) {
  const d = parseUtc(utcIso);
  if (!d) return "";
  const diffSec = Math.round((d - new Date()) / 1000);
  const abs = Math.abs(diffSec);

  for (const [unit, secondsInUnit] of RELATIVE_UNITS) {
    if (abs >= secondsInUnit) {
      const value = Math.round(diffSec / secondsInUnit);
      return new Intl.RelativeTimeFormat(undefined, { numeric: "auto" }).format(value, unit);
    }
  }
  return "just now";
}
