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

function userTimezone() {
  const meta = document.querySelector('meta[name="user-timezone"]');
  return meta && meta.content ? meta.content : undefined;
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

export function toLocalInputValue(utcIso) {
  const d = parseUtc(utcIso);
  if (!d) return "";
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function fromLocalInputValue(localValue) {
  if (!localValue) return null;
  return new Date(localValue).toISOString();
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
