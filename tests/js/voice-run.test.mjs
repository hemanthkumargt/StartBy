// Stop/Brief races in voice.js, with a fake speechSynthesis that records what it is
// asked to say and lets the test fire (or delay) the callbacks a real browser would.
import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import test from "node:test";

const spoken = [];
let cancels = 0;
const fake = {
  getVoices: () => [{ name: "Samantha", lang: "en-US", localService: true }],
  addEventListener() {},
  speak(u) {
    spoken.push(u);
  },
  cancel() {
    cancels += 1;
  },
};
globalThis.window = { speechSynthesis: fake, addEventListener() {} };
globalThis.document = { getElementById: () => null, addEventListener() {} };
globalThis.SpeechSynthesisUtterance = class {
  constructor(text) {
    this.text = text;
  }
};
const dir = mkdtempSync(join(tmpdir(), "startby-run-"));
writeFileSync(join(dir, "api.mjs"), "export async function apiFetch() { return {}; }");
writeFileSync(join(dir, "toast.mjs"), "export function showToast() {}");
writeFileSync(join(dir, "voice-input.mjs"), "export function createVoiceInput() { return {}; }");
const src = readFileSync(new URL("../../app/static/js/voice.js", import.meta.url), "utf8")
  .replace('"./api.js"', '"./api.mjs"')
  .replace('"./toast.js"', '"./toast.mjs"')
  .replace('"./voice-input.js"', '"./voice-input.mjs"');
writeFileSync(join(dir, "voice.mjs"), src);
const voice = await import(pathToFileURL(join(dir, "voice.mjs")).href);

const reset = () => {
  spoken.length = 0;
  cancels = 0;
};

test("speaking queues one utterance per sentence", async () => {
  reset();
  const token = voice.currentRun();
  assert.equal(await voice.speak("One. Two. Three.", { token }), true);
  assert.deepEqual(spoken.map((u) => u.text), ["One.", "Two.", "Three."]);
  assert.equal(spoken[0].voice.name, "Samantha");
});

test("Stop pressed before the voices/fetch finished means nothing is ever spoken", async () => {
  reset();
  const token = voice.currentRun();
  voice.stopSpeaking(); // user pressed Stop; the run is now stale
  assert.equal(await voice.speak("Should not be heard.", { token }), false);
  assert.equal(spoken.length, 0);
});

test("a late callback from a cancelled run cannot reset the newer run", async () => {
  reset();
  let endedOld = 0;
  let endedNew = 0;
  const oldToken = voice.currentRun();
  await voice.speak("Old one.", { token: oldToken, onEnd: () => endedOld++ });
  const oldLast = spoken[spoken.length - 1];
  voice.stopSpeaking(); // Stop...
  const newToken = voice.currentRun();
  await voice.speak("New one.", { token: newToken, onEnd: () => endedNew++ }); // ...then Brief again
  oldLast.onerror({ error: "canceled" }); // the browser reports the old utterance late
  assert.equal(endedOld, 0, "stale callback must be ignored");
  assert.equal(endedNew, 0, "and must not end the new run");
  spoken[spoken.length - 1].onend(); // the new run really finishes
  assert.equal(endedNew, 1);
});
