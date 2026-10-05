// Run by tests/test_js.py with a DIFFERENT process TZ than the user's saved
// zone, which is exactly the situation that used to shift deadlines.
import assert from "node:assert/strict";
import test from "node:test";

let zone = "Asia/Kolkata";
globalThis.document = {
  querySelector: (sel) => (sel.includes("user-timezone") ? { content: zone } : null),
};
// The app's modules are plain .js files without a package.json "type", so Node
// would load them as CommonJS. Import a copy named .mjs instead (no change to
// what is served to browsers).
import { copyFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const scratch = mkdtempSync(join(tmpdir(), "startby-js-"));
copyFileSync(new URL("../../app/static/js/datetime.js", import.meta.url), join(scratch, "datetime.mjs"));
const { toLocalInputValue, fromLocalInputValue, formatDateTime, DateInputError } = await import(
  pathToFileURL(join(scratch, "datetime.mjs")).href
);

test("typed wall time converts to UTC using the SAVED zone, not the browser's", () => {
  zone = "Asia/Kolkata";
  assert.equal(fromLocalInputValue("2026-10-09T17:00"), "2026-10-09T11:30:00.000Z");
  zone = "America/New_York";
  assert.equal(fromLocalInputValue("2026-10-09T17:00"), "2026-10-09T21:00:00.000Z");
});

test("the edit form shows the same clock time the card shows", () => {
  zone = "America/New_York";
  const stored = "2026-10-09T21:00:00"; // naive UTC, as the API sends it
  assert.equal(toLocalInputValue(stored), "2026-10-09T17:00");
  assert.match(formatDateTime(stored), /5:00\s?pm/i);
});

test("round trip is stable across zones and seasons", () => {
  for (const z of ["Asia/Kolkata", "America/New_York", "Europe/London", "Asia/Kathmandu", "UTC", "Pacific/Auckland"]) {
    zone = z;
    for (const wall of ["2026-01-15T09:30", "2026-07-15T23:45", "2026-10-09T00:00", "2026-12-31T23:59"]) {
      assert.equal(toLocalInputValue(fromLocalInputValue(wall)), wall, `${z} ${wall}`);
    }
  }
});

test("DST: spring-forward gap and autumn overlap still produce valid instants", () => {
  zone = "America/New_York";
  const gap = fromLocalInputValue("2026-03-08T02:30"); // does not exist
  assert.ok(!Number.isNaN(Date.parse(gap)));
  const overlap = fromLocalInputValue("2026-11-01T01:30"); // happens twice
  assert.ok(["2026-11-01T05:30:00.000Z", "2026-11-01T06:30:00.000Z"].includes(overlap));
  zone = "Europe/London";
  assert.equal(fromLocalInputValue("2026-07-01T12:00"), "2026-07-01T11:00:00.000Z");
});

test("an empty field means no deadline; a mistyped one is an error, never silently null", () => {
  zone = "Asia/Kolkata";
  assert.equal(fromLocalInputValue(""), null);
  assert.equal(fromLocalInputValue(null), null);
  for (const bad of ["not a date", "0026-10-09T17:00", "20266-10-09T17:00", "275760-09-13T00:00", "1999-12-31T10:00", "2101-01-01T00:00", "2026-10-09"]) {
    assert.throws(() => fromLocalInputValue(bad), DateInputError, bad);
  }
  assert.equal(toLocalInputValue(null), "");
});

test("years at the edges of the allowed window convert", () => {
  zone = "UTC";
  assert.equal(fromLocalInputValue("2000-01-01T00:00"), "2000-01-01T00:00:00.000Z");
  assert.equal(fromLocalInputValue("2100-12-31T23:59"), "2100-12-31T23:59:00.000Z");
});

test("a zone this browser's ICU does not know falls back instead of throwing", () => {
  zone = "Mars/Olympus_Mons";
  assert.doesNotThrow(() => formatDateTime("2026-10-09T11:30:00"));
  assert.doesNotThrow(() => toLocalInputValue("2026-10-09T11:30:00"));
  assert.doesNotThrow(() => fromLocalInputValue("2026-10-09T17:00"));
});
