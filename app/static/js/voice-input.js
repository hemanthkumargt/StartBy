// One microphone button, shared by Smart Capture and the assistant's "Ask" box.
// Two routes, chosen at run time:
//   1. the browser's own speech recognition (Chrome, Edge, Safari): instant, free;
//   2. record audio and have the server transcribe it (Brave, Firefox, or when 1
//      fails): needs a Gemini key on the server.
// The words are only handed to `onTranscript`; what happens next (preview-and-confirm,
// or a read-only answer) is the caller's business.
import { apiFetch } from "./api.js";

const MAX_RECORDING_MS = 60_000;

export function pickRecorderMime(isSupported) {
  return (
    ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"].find((t) => isSupported(t)) ||
    ""
  );
}

export function friendlyMicError(name) {
  switch (name) {
    case "not-allowed":
    case "NotAllowedError":
    case "service-not-allowed":
      return "Microphone access is blocked. Allow it in your browser's site settings, then try again.";
    case "no-speech":
      return "I didn't hear anything. Tap Speak and try again.";
    case "audio-capture":
    case "NotFoundError":
      return "No microphone was found on this device.";
    case "network":
      return "Speech recognition couldn't reach its service.";
    default:
      return "Voice input didn't work this time. You can type instead.";
  }
}

const DEFAULT_IDLE_STOP_MS = 2200;

/**
 * @param {{button: HTMLElement, label: HTMLElement, statusEl: HTMLElement,
 *          onTranscript: (text: string) => void, onLive?: (text: string) => void,
 *          idleLabel?: string, unsupportedMessage?: string, idleStopMs?: number}} opts
 */
export function createVoiceInput({
  button,
  label,
  statusEl,
  onTranscript,
  onLive,
  idleLabel = "Speak",
  unsupportedMessage,
  idleStopMs = DEFAULT_IDLE_STOP_MS,
}) {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const canRecord = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder);
  let mode = Recognition ? "native" : canRecord ? "recorder" : null;
  let active = null; // { stop() } while listening
  let starting = false; // set synchronously on click: covers the permission prompt
  let cancelled = false; // the page was left / stop requested while still starting
  let busy = false;

  const say = (message) => {
    statusEl.textContent = message;
  };
  const setListening = (on) => {
    button.setAttribute("aria-pressed", String(on));
    button.classList.toggle("is-listening", on);
    label.textContent = on ? "Stop" : idleLabel;
  };
  const reset = () => {
    setListening(false);
    active = null;
    starting = false;
  };

  function finish(transcript) {
    const text = (transcript || "").trim();
    if (!text) {
      say("I didn't catch any words. Tap Speak and try again.");
      return;
    }
    onTranscript(text);
  }

  function startNative() {
    const rec = new Recognition();
    rec.lang = navigator.language || "en-IN";
    rec.interimResults = true;
    // continuous + our own idle timer: "continuous = false" ended at the first breath
    // and sent half a sentence; this waits for ~2 seconds of silence instead.
    rec.continuous = true;
    let transcript = "";
    let failed = false;
    let idle = null;
    const armIdle = () => {
      clearTimeout(idle);
      idle = setTimeout(() => rec.stop(), idleStopMs);
    };
    rec.onresult = (event) => {
      transcript = Array.from(event.results)
        .map((r) => r[0].transcript)
        .join(" ");
      if (onLive) onLive(transcript);
      armIdle();
    };
    rec.onerror = (event) => {
      failed = true;
      clearTimeout(idle);
      reset();
      // Brave and some Linux builds expose the API but cannot reach the service.
      if ((event.error === "network" || event.error === "service-not-allowed") && canRecord) {
        mode = "recorder";
        say("Built-in speech recognition isn't available in this browser; switching to recording. Tap Speak again.");
        return;
      }
      say(friendlyMicError(event.error));
    };
    rec.onend = () => {
      clearTimeout(idle);
      reset();
      if (!failed) finish(transcript);
    };
    active = { stop: () => rec.stop() };
    starting = false;
    setListening(true);
    say("Listening… pause when you are done, or tap Stop.");
    try {
      rec.start();
      armIdle(); // also ends cleanly if nothing at all is said
    } catch {
      reset();
      say(friendlyMicError("other"));
    }
  }

  async function startRecorder() {
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      reset();
      say(friendlyMicError(err.name));
      return;
    }
    const closeStream = () => stream.getTracks().forEach((t) => t.stop()); // releases the mic indicator
    if (cancelled) {
      // Stop was pressed or the page was left while the permission prompt was open.
      closeStream();
      reset();
      return;
    }
    let recorder;
    try {
      const mimeType = pickRecorderMime((t) => MediaRecorder.isTypeSupported(t));
      recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
    } catch {
      closeStream();
      reset();
      say(friendlyMicError("other"));
      return;
    }
    const chunks = [];
    let timer = null;
    recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    recorder.onerror = () => {
      clearTimeout(timer);
      closeStream();
      reset();
      say(friendlyMicError("other"));
    };
    recorder.onstop = async () => {
      clearTimeout(timer);
      closeStream();
      reset();
      busy = true;
      button.disabled = true;
      say("Transcribing…");
      try {
        const type = (recorder.mimeType || "audio/webm").split(";")[0];
        const body = new FormData();
        body.append("audio", new Blob(chunks, { type }), `voice.${type.split("/")[1] || "webm"}`);
        const { text } = await apiFetch("/api/voice/transcribe", { method: "POST", body });
        finish(text);
      } catch (err) {
        say(err.message);
      } finally {
        busy = false;
        button.disabled = false;
      }
    };
    timer = setTimeout(() => recorder.state === "recording" && recorder.stop(), MAX_RECORDING_MS);
    active = { stop: () => recorder.state === "recording" && recorder.stop() };
    starting = false;
    setListening(true);
    say("Recording… tap Stop when you are done (up to a minute).");
    try {
      recorder.start();
    } catch {
      clearTimeout(timer);
      closeStream();
      reset();
      say(friendlyMicError("other"));
    }
  }

  if (!mode) {
    button.disabled = true;
    say(unsupportedMessage || "This browser can't take voice input. Type instead.");
  }

  button.addEventListener("click", () => {
    if (busy) return;
    if (active) {
      active.stop();
      return;
    }
    if (starting) {
      cancelled = true; // a second tap while the permission prompt is open means "never mind"
      return;
    }
    cancelled = false;
    starting = true; // synchronous: a fast double-click can no longer open two streams
    if (mode === "native") startNative();
    else startRecorder();
  });

  // Leaving the page must not leave the microphone open — including while the
  // browser's permission prompt is still waiting for an answer.
  window.addEventListener("pagehide", () => {
    cancelled = true;
    if (active) active.stop();
  });

  return { supported: !!mode, say };
}
