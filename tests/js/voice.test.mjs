import assert from "node:assert/strict";
import { copyFileSync, mkdtempSync, writeFileSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import test from "node:test";

// voice.js touches `window`/`document` at import; give it inert stand-ins and
// stub its two imports (the app's modules are .js files Node would treat as CJS).
globalThis.window = { addEventListener() {} };
globalThis.document = { getElementById: () => null, addEventListener() {} };
const dir = mkdtempSync(join(tmpdir(), "startby-voice-"));
writeFileSync(join(dir, "api.mjs"), "export async function apiFetch() { return {}; }");
writeFileSync(join(dir, "toast.mjs"), "export function showToast() {}");
writeFileSync(join(dir, "voice-input.mjs"), "export function createVoiceInput() { return {}; }");
const src = readFileSync(new URL("../../app/static/js/voice.js", import.meta.url), "utf8")
  .replace('"./api.js"', '"./api.mjs"')
  .replace('"./toast.js"', '"./toast.mjs"')
  .replace('"./voice-input.js"', '"./voice-input.mjs"');
writeFileSync(join(dir, "voice.mjs"), src);
const { splitSentences, pickVoice } = await import(pathToFileURL(join(dir, "voice.mjs")).href);

test("long scripts are split into sentences (Chrome cuts long utterances off)", () => {
  assert.deepEqual(splitSentences("Good morning, Ada. One thing needs you. Start now!"), [
    "Good morning, Ada.",
    "One thing needs you.",
    "Start now!",
  ]);
  assert.deepEqual(splitSentences("No punctuation at all"), ["No punctuation at all"]);
  assert.deepEqual(splitSentences("Trailing words. And more"), ["Trailing words.", "And more"]);
  assert.deepEqual(splitSentences(""), [""].filter(Boolean));
});

test("a titled sentence with abbreviations still splits only at terminators", () => {
  assert.equal(splitSentences('Read "Hamlet". Then rest.').length, 2);
});

const v = (name, lang, localService = true) => ({ name, lang, localService });

test("prefers a natural English voice, then any English, then anything", () => {
  const voices = [v("Alex", "en-US"), v("Samantha", "en-US"), v("Thomas", "fr-FR"), v("Google UK English Female", "en-GB", false)];
  assert.ok(["Samantha", "Google UK English Female"].includes(pickVoice(voices).name));
  assert.equal(pickVoice([v("Thomas", "fr-FR")]).name, "Thomas");
  assert.equal(pickVoice([]), null);
});

test("an English voice beats a non-English one even if the other sounds nicer", () => {
  assert.equal(pickVoice([v("Samantha Premium", "de-DE"), v("Plain", "en-US")]).name, "Plain");
});

test("a full stop inside a word never ends a sentence (v2.0, 4.5, a@b.co)", () => {
  assert.deepEqual(splitSentences("1. Ship v2.0 now. Same deal, start it now."), [
    "1.",
    "Ship v2.0 now.",
    "Same deal, start it now.",
  ]);
  assert.deepEqual(splitSentences("Read ch. 3 of 4.5 pages."), ["Read ch.", "3 of 4.5 pages."]);
  assert.deepEqual(splitSentences("Email a@b.co today."), ["Email a@b.co today."]);
  // nothing is ever lost: the pieces rejoin to the original text
  const text = "Ship v2.0 now! Why? Because 4.5 > 4. Done";
  assert.equal(splitSentences(text).join(" "), text);
});
