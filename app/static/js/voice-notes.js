// The Voice Notes page: record -> save the transcript -> read / delete / turn into tasks.
// The microphone itself is the shared voice-input.js. Saving a note never creates a
// task; "Turn into tasks" only hands the text to Smart Capture, which previews first (I14).
import { apiFetch } from "./api.js";
import { formatDateTime } from "./datetime.js";
import { createVoiceInput } from "./voice-input.js";
import { showToast } from "./toast.js";

const root = document.getElementById("vnotes");

if (root) {
  const listEl = document.getElementById("vnote-list");
  const emptyEl = document.getElementById("vnote-empty");
  const countEl = document.getElementById("vnote-count");
  const detailEl = document.getElementById("vnote-detail");
  const placeholderEl = document.getElementById("vnote-placeholder");
  const titleEl = document.getElementById("vnote-detail-title");
  const timeEl = document.getElementById("vnote-detail-time");
  const textEl = document.getElementById("vnote-detail-text");
  const btn = document.getElementById("vnote-mic-btn");
  const headline = document.getElementById("vnote-headline");
  const liveEl = document.getElementById("vnote-live");
  const statusEl = document.getElementById("vnote-status");

  let notes = [];
  let selected = null; // the full note shown on the right

  function renderList() {
    listEl.replaceChildren();
    for (const n of notes) {
      const li = document.createElement("li");
      const b = document.createElement("button");
      b.type = "button";
      b.className = "vnotes__item" + (selected && selected.id === n.id ? " is-active" : "");
      b.dataset.id = String(n.id);
      const t = document.createElement("span");
      t.className = "vnotes__item-title";
      t.textContent = n.title;
      const p = document.createElement("span");
      p.className = "vnotes__item-preview";
      p.textContent = n.preview;
      const d = document.createElement("span");
      d.className = "vnotes__item-time";
      d.textContent = formatDateTime(n.created_at);
      b.append(t, p, d);
      b.addEventListener("click", () => open(n.id));
      li.append(b);
      listEl.append(li);
    }
    emptyEl.hidden = notes.length > 0;
    countEl.textContent = notes.length ? String(notes.length) : "";
  }

  function showDetail(note) {
    selected = note;
    titleEl.textContent = note.title;
    timeEl.textContent = formatDateTime(note.created_at);
    textEl.textContent = note.transcript; // textContent: a note can contain anything
    detailEl.hidden = false;
    placeholderEl.hidden = true;
    root.classList.add("has-detail");
    renderList();
  }

  function closeDetail() {
    selected = null;
    detailEl.hidden = true;
    placeholderEl.hidden = false;
    root.classList.remove("has-detail");
    renderList();
  }

  async function open(id) {
    try {
      showDetail(await apiFetch(`/api/voice/notes/${id}`));
    } catch (err) {
      showToast(err.message);
    }
  }

  async function load() {
    try {
      notes = (await apiFetch("/api/voice/notes")).notes;
    } catch (err) {
      showToast(err.message);
    }
    renderList();
  }

  async function save(transcript) {
    try {
      const note = await apiFetch("/api/voice/notes", {
        method: "POST",
        body: JSON.stringify({ transcript }),
      });
      notes.unshift({ id: note.id, title: note.title, created_at: note.created_at, preview: note.transcript.slice(0, 140) });
      showDetail(note);
      headline.textContent = "Saved. Tap to record another";
      statusEl.textContent = "Your note is saved below.";
    } catch (err) {
      headline.textContent = "Not saved";
      statusEl.textContent = err.message;
      showToast(err.message);
    }
  }

  createVoiceInput({
    button: btn,
    label: document.getElementById("vnote-mic-label"),
    statusEl,
    idleLabel: "Record",
    idleStopMs: 3500, // pauses while thinking are normal in a note
    unsupportedMessage: "This browser can't record. Open StartBy in Chrome, Edge or Safari.",
    onLive: (spoken) => {
      headline.textContent = "Listening…";
      liveEl.textContent = spoken;
    },
    onTranscript: async (spoken) => {
      liveEl.textContent = "";
      if (spoken.trim()) await save(spoken);
    },
  });

  document.getElementById("vnote-back").addEventListener("click", closeDetail);

  document.getElementById("vnote-copy").addEventListener("click", async () => {
    if (!selected) return;
    try {
      await navigator.clipboard.writeText(selected.transcript);
      showToast("Copied.", "success");
    } catch {
      showToast("Couldn't copy. Select the text and copy it by hand.");
    }
  });

  document.getElementById("vnote-to-tasks").addEventListener("click", () => {
    if (!selected) return;
    try {
      sessionStorage.setItem("startby-capture-text", selected.transcript);
    } catch {
      /* private mode: Smart Capture just opens empty */
    }
    window.location.href = "/capture";
  });

  document.getElementById("vnote-delete").addEventListener("click", async () => {
    if (!selected || !window.confirm("Delete this voice note?")) return;
    try {
      await apiFetch(`/api/voice/notes/${selected.id}`, { method: "DELETE" });
      notes = notes.filter((n) => n.id !== selected.id);
      closeDetail();
      showToast("Note deleted.", "success");
    } catch (err) {
      showToast(err.message);
    }
  });

  load();
}
