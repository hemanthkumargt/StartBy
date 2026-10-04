// The shared microphone button, with fake browser APIs so every awkward moment can
// be reproduced: double taps during the permission prompt, leaving the page, a
// recorder that refuses to start, a recogniser that stops listening.
import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import test from "node:test";

const handlers = {}; // window event handlers by name
globalThis.window = { addEventListener: (n, f) => (handlers[n] = f) };
globalThis.navigator = { language: "en-IN" };
globalThis.FormData = class {
  append() {}
};
globalThis.Blob = class {};
globalThis.__api = async () => ({ text: "hello world" });

const dir = mkdtempSync(join(tmpdir(), "startby-vin-"));
writeFileSync(join(dir, "api.mjs"), "export const apiFetch = (...a) => globalThis.__api(...a);");
const src = readFileSync(new URL("../../app/static/js/voice-input.js", import.meta.url), "utf8").replace(
  '"./api.js"',
  '"./api.mjs"'
);
writeFileSync(join(dir, "vin.mjs"), src);
const { createVoiceInput, pickRecorderMime, friendlyMicError } = await import(pathToFileURL(join(dir, "vin.mjs")).href);

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function ui() {
  const el = { clicks: [], attrs: {}, classes: new Set(), disabled: false };
  el.button = {
    addEventListener: (n, f) => n === "click" && el.clicks.push(f),
    setAttribute: (k, v) => (el.attrs[k] = v),
    classList: { toggle: (c, on) => (on ? el.classes.add(c) : el.classes.delete(c)) },
    get disabled() {
      return el.disabled;
    },
    set disabled(v) {
      el.disabled = v;
    },
  };
  el.label = { textContent: "Speak" };
  el.status = { textContent: "" };
  el.click = () => el.clicks.forEach((f) => f());
  return el;
}

function fakeMedia({ recorderThrows = false } = {}) {
  const m = { opened: 0, stopped: 0, resolveStream: null, recorders: [] };
  globalThis.navigator.mediaDevices = {
    getUserMedia: () =>
      new Promise((resolve) => {
        m.opened += 1;
        m.resolveStream = () => resolve({ getTracks: () => [{ stop: () => (m.stopped += 1) }] });
      }),
  };
  globalThis.window.MediaRecorder = globalThis.MediaRecorder = class {
    static isTypeSupported = (t) => t === "audio/webm";
    constructor() {
      if (recorderThrows) throw new Error("unsupported");
      this.state = "inactive";
      this.mimeType = "audio/webm";
      m.recorders.push(this);
    }
    start() {
      this.state = "recording";
    }
    stop() {
      this.state = "inactive";
      this.ondataavailable?.({ data: { size: 4 } });
      this.onstop?.();
    }
  };
  delete globalThis.window.SpeechRecognition;
  delete globalThis.window.webkitSpeechRecognition;
  return m;
}

function build(extra = {}) {
  const e = ui();
  const got = [];
  const api = createVoiceInput({ button: e.button, label: e.label, statusEl: e.status, onTranscript: (t) => got.push(t), ...extra });
  return { e, got, api };
}

test("recorder mime: first supported type wins (webm on Chrome/Brave, mp4 on Safari)", () => {
  assert.equal(pickRecorderMime((t) => t.startsWith("audio/webm")), "audio/webm;codecs=opus");
  assert.equal(pickRecorderMime((t) => t === "audio/mp4"), "audio/mp4");
  assert.equal(pickRecorderMime(() => false), "");
});

test("mic errors become sentences a person can act on", () => {
  assert.match(friendlyMicError("not-allowed"), /blocked/);
  assert.match(friendlyMicError("NotAllowedError"), /blocked/);
  assert.match(friendlyMicError("no-speech"), /didn't hear/);
  assert.match(friendlyMicError("NotFoundError"), /No microphone/);
  assert.match(friendlyMicError("network"), /reach/);
  assert.match(friendlyMicError("whatever"), /type instead/);
});

test("no speech API and no recorder: the button is disabled with an explanation", () => {
  fakeMedia();
  delete globalThis.navigator.mediaDevices;
  delete globalThis.window.MediaRecorder;
  delete globalThis.MediaRecorder;
  const { e, api } = build();
  assert.equal(api.supported, false);
  assert.equal(e.disabled, true);
  assert.match(e.status.textContent, /can't take voice input/);
});

test("recording happy path: speak, stop, transcript delivered, microphone released", async () => {
  const media = fakeMedia();
  const { e, got } = build();
  e.click();
  media.resolveStream();
  await sleep(5);
  assert.equal(e.attrs["aria-pressed"], "true");
  assert.equal(e.label.textContent, "Stop");
  e.click(); // Stop
  await sleep(10);
  assert.deepEqual(got, ["hello world"]);
  assert.equal(media.stopped, 1);
  assert.equal(e.attrs["aria-pressed"], "false");
  assert.equal(e.label.textContent, "Speak");
  assert.equal(e.disabled, false);
});

test("a fast double tap during the permission prompt opens ONE microphone, not two", async () => {
  const media = fakeMedia();
  const { e } = build();
  e.click();
  e.click(); // second tap while the prompt is still open = "never mind"
  assert.equal(media.opened, 1);
  media.resolveStream();
  await sleep(5);
  assert.equal(media.stopped, 1, "the granted stream is closed straight away");
  assert.equal(e.attrs["aria-pressed"], "false");
});

test("leaving the page while the permission prompt is open still releases the microphone", async () => {
  const media = fakeMedia();
  const { e } = build();
  e.click();
  handlers.pagehide();
  media.resolveStream();
  await sleep(5);
  assert.equal(media.stopped, 1);
  assert.equal(e.label.textContent, "Speak");
});

test("a recorder that refuses to start releases the microphone and resets the button", async () => {
  const media = fakeMedia({ recorderThrows: true });
  const { e } = build();
  e.click();
  media.resolveStream();
  await sleep(5);
  assert.equal(media.stopped, 1);
  assert.equal(e.label.textContent, "Speak");
  assert.match(e.status.textContent, /type instead/);
});

test("permission denied gives a friendly message and the button works again", async () => {
  const media = fakeMedia();
  globalThis.navigator.mediaDevices.getUserMedia = () => Promise.reject(Object.assign(new Error("x"), { name: "NotAllowedError" }));
  const { e } = build();
  e.click();
  await sleep(5);
  assert.match(e.status.textContent, /blocked/);
  assert.equal(e.label.textContent, "Speak");
  assert.equal(media.opened, 0);
  e.click(); // can try again
});

class FakeRecognition {
  static instances = [];
  constructor() {
    FakeRecognition.instances.push(this);
    this.stopped = 0;
  }
  start() {}
  stop() {
    this.stopped += 1;
    queueMicrotask(() => this.onend?.());
  }
  say(text) {
    this.onresult?.({ results: [[{ transcript: text }]] });
  }
}

function withNative() {
  FakeRecognition.instances.length = 0;
  fakeMedia(); // (this removes any speech API, so install ours afterwards)
  globalThis.window.SpeechRecognition = FakeRecognition;
}

test("native recognition keeps listening through a pause, then stops after the idle delay", async () => {
  withNative();
  const live = [];
  const { e, got } = build({ idleStopMs: 40, onLive: (t) => live.push(t) });
  e.click();
  const rec = FakeRecognition.instances[0];
  assert.equal(rec.continuous, true, "must not end at the first breath");
  rec.say("submit the lab record");
  await sleep(20);
  assert.equal(rec.stopped, 0, "a short pause does not end it");
  rec.say("submit the lab record by friday");
  await sleep(80);
  assert.equal(rec.stopped, 1, "silence does");
  await sleep(5);
  assert.deepEqual(live, ["submit the lab record", "submit the lab record by friday"]);
  assert.deepEqual(got, ["submit the lab record by friday"]);
});

test("native recognition that hears nothing ends cleanly with a helpful message", async () => {
  withNative();
  const { e, got } = build({ idleStopMs: 20 });
  e.click();
  await sleep(60);
  assert.deepEqual(got, []);
  assert.match(e.status.textContent, /didn't catch/);
  assert.equal(e.label.textContent, "Speak");
});

test("a 'network' failure (Brave) switches to recording instead of giving up", async () => {
  withNative();
  const media = fakeMedia(); // recorder available too
  globalThis.window.SpeechRecognition = FakeRecognition;
  const { e, got } = build();
  e.click();
  FakeRecognition.instances[0].onerror({ error: "network" });
  assert.match(e.status.textContent, /switching to recording/);
  e.click(); // now records
  media.resolveStream();
  await sleep(5);
  assert.equal(e.label.textContent, "Stop");
  e.click();
  await sleep(10);
  assert.deepEqual(got, ["hello world"]);
});
