import { apiFetch } from "./api.js";
import { showToast } from "./toast.js";
import { DateInputError, fromLocalInputValue, toLocalInputValue } from "./datetime.js";

const form = document.getElementById("capture-form");
const textEl = document.getElementById("capture-text");
const fileEl = document.getElementById("capture-file");
const errorEl = document.getElementById("capture-error");
const extractBtn = document.getElementById("capture-extract-btn");
const results = document.getElementById("capture-results");
const banner = document.getElementById("capture-banner");
const draftList = document.getElementById("capture-drafts");
const emptyEl = document.getElementById("capture-empty");
const saveBtn = document.getElementById("capture-save-btn");
const discardBtn = document.getElementById("capture-discard-btn");

// The estimate input is always rendered: the server drops estimate_hours
// itself when FEATURE_ESTIMATES is off, so no client-side flag check is needed.
function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  Object.assign(node, props);
  for (const child of children) node.append(child);
  return node;
}

function showError(message) {
  errorEl.textContent = message;
  errorEl.hidden = false;
}

function renderDraft(draft) {
  const row = el("li", { className: "capture-draft" });

  const check = el("input", { type: "checkbox", checked: true, className: "capture-draft__check" });
  check.setAttribute("aria-label", "Include this task");

  const title = el("input", { type: "text", value: draft.title, maxLength: 200 });
  title.setAttribute("aria-label", "Task title");
  title.name = "title";

  const tag = el("select", {}, ["work", "study", "personal"].map((t) => el("option", { value: t, textContent: t })));
  tag.value = draft.tag;
  tag.setAttribute("aria-label", "Tag");
  tag.name = "tag";

  const due = el("input", { type: "datetime-local", value: toLocalInputValue(draft.due_at) });
  due.setAttribute("aria-label", "Deadline");
  due.name = "due_at";

  const est = el("input", {
    type: "number", step: "0.25", min: "0.25", max: "100",
    value: draft.estimate_hours ?? "", placeholder: "hrs",
  });
  est.setAttribute("aria-label", "Estimated hours");
  est.name = "estimate_hours";

  row.append(check, title, tag, due, est);
  const note = el("p", { className: "capture-draft__flag" });
  note.setAttribute("role", "status");
  // The extractor only returns dates it is sure about, so a blank date means
  // "nothing recognised" and a past date means "check this" — say so, rather
  // than letting the row look as trustworthy as one with a good deadline.
  const refreshFlag = () => {
    let value = null;
    let invalid = false;
    try {
      value = fromLocalInputValue(due.value);
    } catch (err) {
      if (!(err instanceof DateInputError)) throw err;
      invalid = true;
    }
    if (invalid) {
      note.textContent = "That date is not valid — use a year between 2000 and 2100.";
    } else if (!value) {
      note.textContent = "No deadline found — add one if this task has a due date.";
    } else if (new Date(value) < new Date()) {
      note.textContent = "This deadline is in the past — check the date.";
    } else if (new Date(value) - new Date() > 90 * 86400000) {
      note.textContent = "This deadline is more than 3 months away — check the date.";
    } else {
      note.textContent = "";
    }
    note.hidden = note.textContent === "";
    due.setAttribute("aria-invalid", note.hidden ? "false" : "true");
  };
  due.addEventListener("input", refreshFlag);
  refreshFlag();
  row.append(note);
  if (draft.notes) row.append(el("p", { className: "capture-draft__notes", textContent: draft.notes }));
  row._read = () => ({
    include: check.checked,
    task: {
      title: title.value,
      tag: tag.value,
      due_at: check.checked ? fromLocalInputValue(due.value) : null,
      estimate_hours: est.value === "" ? null : Number(est.value),
      notes: draft.notes ?? null,
    },
  });
  return row;
}

function showResults(data) {
  draftList.replaceChildren(...data.tasks.map(renderDraft));
  emptyEl.hidden = data.tasks.length > 0;
  saveBtn.hidden = data.tasks.length === 0;
  banner.textContent =
    data.source === "gemini"
      ? "Drafted by Gemini — check each row before saving."
      : "AI was unavailable, so a simple extractor was used. Titles and dates may need fixing.";
  banner.dataset.source = data.source;
  results.hidden = false;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  errorEl.hidden = true;
  const file = fileEl.files[0];
  let options;
  if (file) {
    const body = new FormData();
    body.append("file", file);
    options = { method: "POST", body };
  } else {
    // data-voice is set by voice-capture.js when the text was dictated, so the server
    // can tidy spoken phrasing ("remind me to ...", "and then ..."). Typing resets it.
    options = {
      method: "POST",
      body: JSON.stringify({ text: textEl.value, voice: form.dataset.voice === "1" }),
    };
  }
  extractBtn.disabled = true;
  extractBtn.textContent = "Extracting…";
  try {
    showResults(await apiFetch("/api/capture/preview", options));
  } catch (err) {
    results.hidden = true;
    showError(err.message);
  } finally {
    extractBtn.disabled = false;
    extractBtn.textContent = "Extract tasks";
  }
});

saveBtn.addEventListener("click", async () => {
  let chosen;
  try {
    chosen = [...draftList.children].map((row) => row._read()).filter((r) => r.include);
  } catch (err) {
    if (!(err instanceof DateInputError)) throw err;
    showError(err.message);
    return;
  }
  if (chosen.length === 0) {
    showError("Tick at least one task to save.");
    return;
  }
  errorEl.hidden = true;
  saveBtn.disabled = true;
  try {
    const { created } = await apiFetch("/api/capture/confirm", {
      method: "POST",
      body: JSON.stringify({ tasks: chosen.map((r) => r.task) }),
    });
    showToast(`${created.length} task${created.length === 1 ? "" : "s"} saved`, "success");
    form.reset();
    results.hidden = true;
    draftList.replaceChildren();
  } catch (err) {
    showError(err.message);
  } finally {
    saveBtn.disabled = false;
  }
});

discardBtn.addEventListener("click", () => {
  if (!confirm("Discard these drafts? Your edits will be lost.")) return;
  results.hidden = true;
  draftList.replaceChildren();
});

// "Add ..." said to the assistant arrives here for the normal review-and-confirm.
const handedOver = sessionStorage.getItem("startby-capture-text");
if (handedOver) {
  sessionStorage.removeItem("startby-capture-text");
  textEl.value = handedOver;
  form.dataset.voice = "1"; // spoken-style phrasing: strip "add ..." / split sentences
  form.requestSubmit();
}
