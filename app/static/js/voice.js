// Spoken briefing. The words always appear on screen (nobody depends on audio);
// speech is an extra, using the device's own voices via the Web Speech API, so
// no audio leaves the browser and nothing here needs an API key.
import { apiFetch } from "./api.js";
import { showToast } from "./toast.js";
import { createVoiceInput } from "./voice-input.js";

const synth = "speechSynthesis" in window ? window.speechSynthesis : null;

// Chrome silently cuts a single long utterance off after ~15 seconds, so the
// script is spoken one sentence at a time. A "." only ends a sentence when whitespace
// or the end follows it, so "v2.0", "4.5" and "a@b.co" stay in one piece.
export function splitSentences(text) {
  return (text.match(/[^]+?(?:[.!?]+(?=\s|$)|$)/g) || [text]).map((s) => s.trim()).filter(Boolean);
}

// Prefer a natural English voice; fall back to whatever the device has.
export function pickVoice(voices, preferredLang = "en") {
  const english = voices.filter((v) => v.lang && v.lang.toLowerCase().startsWith(preferredLang));
  const rank = (v) => {
    const name = v.name.toLowerCase();
    let score = 0;
    if (/(female|samantha|zira|aria|jenny|google uk english female|karen|moira|tessa|veena|neerja)/.test(name)) score += 3;
    if (/(natural|neural|enhanced|premium)/.test(name)) score += 2;
    if (v.lang.toLowerCase().startsWith("en-in") || v.lang.toLowerCase().startsWith("en-gb")) score += 1;
    if (v.localService) score += 1;
    return score;
  };
  return english.sort((a, b) => rank(b) - rank(a))[0] || voices[0] || null;
}

function voicesReady() {
  return new Promise((resolve) => {
    const have = synth.getVoices();
    if (have.length) return resolve(have);
    const done = () => resolve(synth.getVoices());
    synth.addEventListener("voiceschanged", done, { once: true });
    setTimeout(done, 800); // some browsers never fire the event
  });
}

let speaking = false;
// Every Brief/Stop bumps this. Anything that finishes later (a fetch, voice loading,
// a cancelled utterance's late `onerror`) checks it still belongs to the current run,
// so a stale callback can't speak after Stop or reset the buttons of a newer run.
let run = 0;
export const currentRun = () => run;

// iPhone Safari only lets a page start speaking from inside a tap handler, and the
// briefing is fetched first (an await), which ends that "user gesture". Speaking a
// silent utterance synchronously on the tap unlocks speech for the rest of the page.
export function primeSpeech() {
  if (!synth) return;
  const u = new SpeechSynthesisUtterance(" ");
  u.volume = 0;
  synth.speak(u);
}

export function stopSpeaking() {
  run += 1;
  if (synth) synth.cancel();
  speaking = false;
}

export async function speak(text, { token = run, onEnd } = {}) {
  if (!synth) return false;
  const voice = pickVoice(await voicesReady());
  if (token !== run) return false; // Stop (or a newer click) happened while voices loaded
  synth.cancel();
  const sentences = splitSentences(text);
  speaking = true;
  sentences.forEach((sentence, index) => {
    const u = new SpeechSynthesisUtterance(sentence);
    if (voice) {
      u.voice = voice;
      u.lang = voice.lang;
    }
    u.rate = 1.02;
    u.pitch = 1;
    if (index === sentences.length - 1) {
      u.onend = u.onerror = () => {
        if (token !== run) return; // a cancelled earlier run reporting in late
        speaking = false;
        if (onEnd) onEnd();
      };
    }
    synth.speak(u);
  });
  return true;
}

const card = document.getElementById("assistant-card");
if (card) {
  const briefBtn = document.getElementById("assistant-brief-btn");
  const stopBtn = document.getElementById("assistant-stop-btn");
  const output = document.getElementById("assistant-output");
  const hint = document.getElementById("assistant-hint");

  const setBusy = (busy) => {
    briefBtn.disabled = busy;
    stopBtn.hidden = !busy;
  };

  if (!synth) hint.textContent = "This browser can't speak aloud, so the briefing is shown as text.";

  briefBtn.addEventListener("click", async () => {
    primeSpeech();
    const token = ++run;
    setBusy(true);
    try {
      const data = await apiFetch("/api/voice/briefing");
      if (token !== run) return; // Stop was pressed while the briefing was loading
      output.textContent = "";
      const p = document.createElement("p");
      p.textContent = data.script;
      output.append(p);
      output.hidden = false;
      const started = await speak(data.script, { token, onEnd: () => setBusy(false) });
      if (!started && token === run) setBusy(false);
    } catch (err) {
      if (token !== run) return;
      showToast(err.message, "error");
      setBusy(false);
    }
  });

  stopBtn.addEventListener("click", () => {
    stopSpeaking();
    setBusy(false);
    briefBtn.focus(); // the Stop button just disappeared; keep keyboard focus somewhere useful
  });

  // ---- Ask: a typed or spoken question, answered from the user's own tasks ----
  const askForm = document.getElementById("assistant-ask-form");
  const askInput = document.getElementById("assistant-ask-input");
  const askBtn = document.getElementById("assistant-ask-btn");
  const micStatus = document.getElementById("assistant-mic-status");

  const show = (question, answer) => {
    output.textContent = "";
    if (question) {
      const q = document.createElement("p");
      q.className = "assistant-card__q";
      q.textContent = question;
      output.append(q);
    }
    const p = document.createElement("p");
    p.textContent = answer;
    output.append(p);
    output.hidden = false;
  };

  askForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const question = askInput.value.trim();
    if (!question) return;
    primeSpeech();
    const token = ++run;
    askBtn.disabled = true;
    try {
      const data = await apiFetch("/api/voice/ask", { method: "POST", body: JSON.stringify({ text: question }) });
      if (token !== run) return;
      show(question, data.answer);
      if (data.action && data.action.type === "capture") {
        // Nothing is created here: Smart Capture shows a draft to review and confirm.
        sessionStorage.setItem("startby-capture-text", data.action.text);
        setTimeout(() => (window.location.href = "/capture"), 1200);
        return;
      }
      askInput.value = "";
      setBusy(true);
      const started = await speak(data.answer, { token, onEnd: () => setBusy(false) });
      if (!started && token === run) setBusy(false);
    } catch (err) {
      if (token !== run) return;
      showToast(err.message, "error");
      setBusy(false);
    } finally {
      askBtn.disabled = false;
    }
  });

  createVoiceInput({
    button: document.getElementById("assistant-mic-btn"),
    label: document.getElementById("assistant-mic-label"),
    statusEl: micStatus,
    unsupportedMessage: "This browser can't take voice input. Type your question instead.",
    onLive: (text) => {
      askInput.value = text;
    },
    onTranscript: (text) => {
      askInput.value = text;
      askForm.requestSubmit();
    },
  });

  // Never keep talking after the user leaves or switches away.
  window.addEventListener("pagehide", stopSpeaking);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden" && !stopBtn.hidden) {
      stopSpeaking();
      setBusy(false);
    }
  });
}
