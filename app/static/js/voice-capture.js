// Dictate tasks into Smart Capture. The microphone itself is the shared
// voice-input.js; this file only decides what to do with the words.
// Either way the words only land in the text box; tasks are created from them only
// after the usual preview + confirm (I14).
import { createVoiceInput } from "./voice-input.js";

export { friendlyMicError, pickRecorderMime } from "./voice-input.js";

const form = document.getElementById("capture-form");
const textEl = document.getElementById("capture-text");
const fileEl = document.getElementById("capture-file");
const btn = document.getElementById("voice-mic-btn");

if (form && textEl && btn) {
  const label = document.getElementById("voice-mic-label");
  const statusEl = document.getElementById("voice-status");
  let prefix = ""; // what was already in the box when dictation started

  // Typing over dictated text turns the "spoken" flag off again.
  textEl.addEventListener("input", () => {
    form.dataset.voice = "";
  });

  // Dictation is ADDED to what is there (a pasted syllabus must not be wiped), as a
  // new line; the box is only read back as "spoken text" when it held nothing else.
  const compose = (spoken) => (prefix ? `${prefix}\n${spoken}` : spoken);

  btn.addEventListener(
    "click",
    () => {
      if (btn.getAttribute("aria-pressed") === "true") return; // tapping Stop, not starting
      prefix = textEl.value.trim();
      if (fileEl && fileEl.files.length) {
        fileEl.value = ""; // a chosen PDF would be uploaded INSTEAD of the dictated text
        statusEl.textContent = "The chosen PDF was cleared so your dictation is used.";
      }
    },
    { capture: true }
  );

  createVoiceInput({
    button: btn,
    label,
    statusEl,
    unsupportedMessage: "This browser can't take voice input. Type or paste your tasks instead.",
    onLive: (spoken) => {
      textEl.value = compose(spoken);
    },
    onTranscript: (spoken) => {
      textEl.value = compose(spoken);
      if (prefix) {
        form.dataset.voice = "";
        statusEl.textContent = "Added to your text. Press Extract tasks when you're ready.";
        return;
      }
      form.dataset.voice = "1";
      statusEl.textContent = "Got it. Drafting your tasks — check them below before saving.";
      form.requestSubmit();
    },
  });
}
