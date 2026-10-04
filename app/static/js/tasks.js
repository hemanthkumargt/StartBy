import { apiFetch } from "./api.js";
import { showToast } from "./toast.js";
import { DateInputError, formatDateTime, fromLocalInputValue, toLocalInputValue } from "./datetime.js";
import { escapeHtml } from "./dom.js";

// risk/start_by only exist in the payload at all when FEATURE_ESTIMATES is
// on (task_service omits both keys entirely when it's off) — their presence
// is the only check needed here, not the flag itself. risk is computed
// server-side (task_service.serialize_task -> estimate_service.compute_risk,
// via timeutil) the same way is_overdue already is, so Adaptive Replanning
// (CLAUDE.md 2.5) needs no client-side time comparison or recompute step: a
// task already past its recommended start time just reads that way (red) on
// the very next render. Text always differs by risk level too, not just
// colour (accessibility: colour is never the only signal).
const RISK_LABEL = { red: "Start now", amber: "Start soon", green: "On track" };

function renderStartBy(task) {
  if (!("risk" in task) || task.risk === "none" || !task.start_by) {
    return "";
  }
  const label = RISK_LABEL[task.risk];
  const detail = task.risk === "red" ? "" : ` — start by ${formatDateTime(task.start_by)}`;
  return `<span class="task-card__start-by task-card__start-by--${task.risk}">${label}${detail}</span>`;
}

// 62.26 -> "2 days 14 hours": people don't read hours to two decimals.
export function describeHours(hours) {
  if (hours < 1) return "less than an hour";
  const whole = Math.round(hours);
  if (whole < 48) return whole === 1 ? "1 hour" : `${whole} hours`;
  const days = Math.floor(whole / 24);
  const rest = whole - days * 24;
  const dayText = days === 1 ? "1 day" : `${days} days`;
  return rest === 0 ? dayText : `${dayText} ${rest === 1 ? "1 hour" : `${rest} hours`}`;
}

// Adaptive Replanning: once the planned start is missed the server sends the
// recomputed plan; say it in words rather than leaving a bare red badge.
function renderReplan(task) {
  if (!task.replan) return "";
  const finish = formatDateTime(task.replan.projected_finish);
  const late = task.replan.late_by_hours > 0
    ? ` That is about ${describeHours(task.replan.late_by_hours)} after the due time — consider moving the deadline.`
    : " That is still before the due time.";
  return `<p class="task-card__replan">Plan updated: start now and you would finish around ${escapeHtml(finish)}.${late}</p>`;
}

// Lucide-style SVG vector icons
const ICONS = {
  zap: `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg>`,
  check: `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>`,
  clock: `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>`,
  tag: `<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"></path><line x1="7" y1="7" x2="7.01" y2="7"></line></svg>`,
  pencil: `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"></path></svg>`,
  trash: `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"></path><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"></path><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"></path></svg>`,
};

// Server-written plain-language answer to "why this start time?" (the same
// text the start-now reminder email carries). A native <details>, so it is
// keyboard- and screen-reader-accessible with no JS, and the text goes
// through escapeHtml like everything else rendered from an API payload.
// Lists re-render wholesale (after every action, and again when a tab
// regains visibility), which would slam shut an explanation the user is in
// the middle of reading — so which ones are open is remembered by task id.
const openExplanations = new Set();

function renderExplanation(task) {
  if (task.status !== "pending" || !task.start_by_explanation) {
    return "";
  }
  return `<details class="task-card__why" ${openExplanations.has(task.id) ? "open" : ""}>
    <summary>Why this start time?</summary>
    <p>${escapeHtml(task.start_by_explanation)}</p>
  </details>`;
}

// Unified task card renderer for both Tasks page and Dashboard priority radar
export function renderTaskCard(task, handlers = {}) {
  const card = document.createElement(handlers.onToggle ? "li" : "div");
  card.className = "task-card";
  card.dataset.taskId = String(task.id);

  const isDone = task.status === "done";
  const badgeClass = isDone ? "badge--done" : task.is_overdue ? "badge--overdue" : "badge--pending";
  const badgeIcon = isDone ? ICONS.check : ICONS.zap;
  const badgeLabel = isDone ? "Done" : task.is_overdue ? "Overdue" : "Pending";

  card.innerHTML = `
    <div class="task-card__main">
      ${handlers.onToggle
      ? `<input type="checkbox" class="task-card__checkbox"
               ${isDone ? "checked" : ""}
               aria-label="Mark '${escapeHtml(task.title)}' as ${isDone ? "pending" : "done"}">`
      : ""
    }
      <div class="task-card__body">
        <p class="task-card__title ${isDone ? "task-card__title--done" : ""}">${escapeHtml(task.title)}</p>
        ${task.notes ? `<p class="task-card__notes">${escapeHtml(task.notes)}</p>` : ""}
        <div class="task-card__meta">
          <span class="tag-chip tag-chip--${task.tag}">${ICONS.tag} <span>${escapeHtml(task.tag)}</span></span>
          <span class="badge ${badgeClass}">${badgeIcon} <span>${badgeLabel}</span></span>
          ${task.due_at ? `<span class="task-card__due">${ICONS.clock} <span>${formatDateTime(task.due_at)}</span></span>` : ""}
          ${renderStartBy(task)}
        </div>
        ${renderReplan(task)}
        ${renderExplanation(task)}
      </div>
    </div>
    ${handlers.onEdit || handlers.onDelete
      ? `<div class="task-card__actions">
             ${handlers.onEdit ? `<button type="button" class="task-card__edit" aria-label="Edit ${escapeHtml(task.title)}">${ICONS.pencil} <span>Edit</span></button>` : ""}
             ${handlers.onDelete ? `<button type="button" class="task-card__delete" aria-label="Delete ${escapeHtml(task.title)}">${ICONS.trash} <span>Delete</span></button>` : ""}
           </div>`
      : ""
    }
  `;

  card.querySelector(".task-card__why")?.addEventListener("toggle", (e) => {
    if (e.target.open) openExplanations.add(task.id);
    else openExplanations.delete(task.id);
  });

  if (handlers.onToggle) {
    const checkbox = card.querySelector(".task-card__checkbox");
    checkbox.addEventListener("change", (e) => {
      e.target.disabled = true;
      handlers.onToggle(task).finally(() => {
        e.target.disabled = false;
      });
    });
  }
  if (handlers.onEdit) {
    card.querySelector(".task-card__edit").addEventListener("click", () => handlers.onEdit(task));
  }
  if (handlers.onDelete) {
    card
      .querySelector(".task-card__delete")
      .addEventListener("click", () => handlers.onDelete(task));
  }

  return card;
}

// Shared with any page that renders a completable task card (tasks.js's own
// list and dashboard.js's "Do this now" card) — one implementation rather
// than each page copying its own complete/reopen POST + error handling.
// I13's per-tag multiplier needs a history of (estimate_hours, actual_hours)
// pairs to learn from — this is where that history gets one data point,
// "one-tap" at the moment of completion rather than a separate form. Only
// asked when there's something to compare against (an estimate was set) and
// only on the pending -> done transition, not plain re-toggles or reopens.
// A JS-created <dialog>, not window.prompt(): prompt() isn't guaranteed to
// be available (it throws rather than blocks in some embedded/automated
// contexts), and a <dialog> matches the app's own modal convention (native
// focus trap + Esc-close, CLAUDE.md quality bar) instead of introducing a
// second, inconsistent kind of popup.
//
// A fresh dialog per call, removed on close — not a reused singleton.
// Reuse was tried first and had two real bugs: (1) dialog.returnValue only
// changes on a method="dialog" submit, so Escape-dismissing a later prompt
// would silently resolve with the PREVIOUS prompt's "save" returnValue
// still set, turning a cancel into an accidental save; (2) two completions
// toggled before either resolves would fight over the one open dialog —
// the second showModal() throws InvalidStateError, and if both are
// eventually answered, each other's close listener can resolve the wrong
// task's Promise with the wrong input. A fresh element per call has no
// shared state for either bug to live in.
const QUICK_ACTUAL_CHOICES = [
  ["Faster", 0.75],
  ["On estimate", 1],
  ["Longer", 1.5],
  ["Twice as long", 2],
];

function promptForActualHours(task) {
  return new Promise((resolve) => {
    const dialog = document.createElement("dialog");
    dialog.className = "task-modal";
    dialog.innerHTML = `
      <form method="dialog">
        <h2 class="actual-hours-prompt__title"></h2>
        <div class="actual-hours-quick" role="group" aria-label="One-tap answers"></div>
        <label for="actual-hours-input">Actual hours (optional)</label>
        <input id="actual-hours-input" type="number" step="0.25" min="0.25" max="100" placeholder="e.g. 2.5">
        <div class="modal-actions">
          <button type="submit" value="cancel" class="btn btn--ghost" formnovalidate>Cancel</button>
          <button type="submit" value="skip" class="btn btn--secondary">Skip</button>
          <button type="submit" value="save" class="btn btn--primary">Save</button>
        </div>
      </form>
    `;
    dialog.querySelector(".actual-hours-prompt__title").textContent =
      `How many hours did "${task.title}" actually take?`;
    const input = dialog.querySelector("#actual-hours-input");
    const saveBtn = dialog.querySelector('button[value="save"]');

    // One-tap answers relative to the estimate: a tap fills the number and saves.
    const quick = dialog.querySelector(".actual-hours-quick");
    for (const [label, factor] of QUICK_ACTUAL_CHOICES) {
      const hours = Math.min(100, Math.max(0.25, Math.round(task.estimate_hours * factor * 4) / 4));
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "btn btn--secondary actual-hours-quick__chip";
      chip.textContent = `${label} · ${hours}h`;
      chip.addEventListener("click", () => {
        input.value = String(hours);
        saveBtn.click();
      });
      quick.appendChild(chip);
    }

    // A single-input form implicitly submits via its first submit button
    // in DOM order on Enter — "Skip" here, since it's visually first —
    // which would silently discard a number the user just typed. Bind
    // Enter to Save explicitly instead of relying on that default.
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        saveBtn.click();
      }
    });

    dialog.addEventListener(
      "close",
      () => {
        const hours = Number(input.value);
        // Esc and the backdrop leave returnValue empty: that is "never mind", the
        // same as the Cancel button. Only Skip and Save go on to complete the task.
        const action = dialog.returnValue || "cancel";
        resolve({
          action,
          hours:
            action === "save" && input.value.trim() !== "" && !Number.isNaN(hours)
              ? hours
              : undefined,
        });
        dialog.remove();
      },
      { once: true }
    );

    document.body.appendChild(dialog);
    dialog.showModal();
    input.focus();
  });
}

export async function toggleComplete(task, onDone) {
  const isCompleting = task.status !== "done";
  const path = isCompleting ? `/api/tasks/${task.id}/complete` : `/api/tasks/${task.id}/reopen`;
  let actualHours;
  if (isCompleting && "estimate_hours" in task && task.estimate_hours != null) {
    const answer = await promptForActualHours(task);
    if (answer.action === "cancel") {
      await onDone(); // re-render so the ticked box goes back to unticked
      return;
    }
    actualHours = answer.hours;
  }
  try {
    await apiFetch(path, {
      method: "POST",
      ...(actualHours !== undefined ? { body: JSON.stringify({ actual_hours: actualHours }) } : {}),
    });
    await onDone();
  } catch (err) {
    showToast(err.message, "error");
  }
}

const taskList = document.getElementById("task-list");
if (taskList) {
  const emptyState = document.getElementById("task-empty-state");
  const searchInput = document.getElementById("task-search");
  const tabButtons = document.querySelectorAll("[data-status-filter]");
  const tagButtons = document.querySelectorAll("[data-tag-filter]");
  const newTaskBtn = document.getElementById("new-task-btn");

  const modal = document.getElementById("task-modal");
  const form = document.getElementById("task-form");
  const formError = document.getElementById("task-form-error");
  const modalTitle = document.getElementById("task-modal-title");
  const saveBtn = document.getElementById("task-save-btn");

  const filters = { status: null, tag: null, q: "" };
  let searchDebounce = null;

  // Dashboard shortcuts link here as /tasks?status=pending or ?tag=study.
  // Only known values are honoured, and the matching tab is shown as selected
  // so the page never says "All" while listing a filtered set.
  const initial = new URLSearchParams(window.location.search);
  function applyInitialFilter(buttons, attr, value) {
    const match = [...buttons].find((b) => b.dataset[attr] && b.dataset[attr] === value);
    if (!match) return null;
    buttons.forEach((b) => b.setAttribute("aria-selected", b === match ? "true" : "false"));
    return value;
  }
  filters.status = applyInitialFilter(tabButtons, "statusFilter", initial.get("status"));
  filters.tag = applyInitialFilter(tagButtons, "tagFilter", initial.get("tag"));
  const openNewOnLoad = initial.get("new") === "1"; // the installed app's "New task" shortcut

  function buildQuery() {
    const params = new URLSearchParams();
    if (filters.status) params.set("status", filters.status);
    if (filters.tag) params.set("tag", filters.tag);
    if (filters.q) params.set("q", filters.q);
    const qs = params.toString();
    return qs ? `/api/tasks?${qs}` : "/api/tasks";
  }

  function openEditModal(task) {
    modalTitle.textContent = "Edit Task";
    form.elements.id.value = task.id;
    form.elements.title.value = task.title;
    form.elements.notes.value = task.notes || "";
    form.elements.tag.value = task.tag;
    form.elements.due_at.value = toLocalInputValue(task.due_at);
    // Remembered so a save that did not touch the deadline does not re-send it:
    // re-sending rewrites the stored instant (seconds, DST-repeated hour), logs a
    // "due date changed" activity row and clears already-sent reminders.
    form.dataset.originalDue = form.elements.due_at.value;
    // Only present when FEATURE_ESTIMATES is on (see tasks.html).
    if (form.elements.estimate_hours) {
      form.elements.estimate_hours.value = task.estimate_hours ?? "";
    }
    if (formError) formError.hidden = true;
    modal.showModal();
    form.elements.title.focus();
  }

  function openCreateModal() {
    modalTitle.textContent = "New Task";
    form.reset();
    form.elements.id.value = "";
    form.dataset.originalDue = "";
    if (formError) formError.hidden = true;
    modal.showModal();
    form.elements.title.focus();
  }

  async function deleteTask(task) {
    if (!confirm(`Delete "${task.title}"? This cannot be undone.`)) return;
    try {
      await apiFetch(`/api/tasks/${task.id}`, { method: "DELETE" });
      showToast("Task deleted", "success");
      await loadTasks();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  let loadSeq = 0;

  async function loadTasks() {
    const seq = ++loadSeq;
    try {
      const tasks = await apiFetch(buildQuery());
      if (seq !== loadSeq) return;
      // The list is rebuilt wholesale; without this a keyboard user who just ticked,
      // edited or deleted something lands on <body> and must tab through the whole
      // page again. Remember the control (by task id + which control) and restore it.
      const active = document.activeElement;
      const focusedCard = active && taskList.contains(active) ? active.closest("[data-task-id]") : null;
      const focusedTaskId = focusedCard ? focusedCard.dataset.taskId : null;
      const focusedClass = focusedCard
        ? ["task-card__checkbox", "task-card__edit", "task-card__delete"].find((c) =>
            active.classList.contains(c)
          )
        : null;
      taskList.innerHTML = "";
      emptyState.hidden = tasks.length > 0;
      for (const task of tasks) {
        taskList.appendChild(
          renderTaskCard(task, {
            onToggle: (t) => toggleComplete(t, loadTasks),
            onEdit: openEditModal,
            onDelete: deleteTask,
          })
        );
      }
      if (focusedTaskId) {
        const again = taskList.querySelector(`[data-task-id="${focusedTaskId}"]`);
        const target =
          (again && focusedClass && again.querySelector(`.${focusedClass}`)) ||
          (again && again.querySelector("button, input"));
        if (target) target.focus();
      }
    } catch (err) {
      if (seq !== loadSeq) return;
      showToast(err.message, "error");
    }
  }

  tabButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      tabButtons.forEach((b) => b.setAttribute("aria-selected", "false"));
      btn.setAttribute("aria-selected", "true");
      filters.status = btn.dataset.statusFilter || null;
      loadTasks();
    });
  });

  tagButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      tagButtons.forEach((b) => b.setAttribute("aria-selected", "false"));
      btn.setAttribute("aria-selected", "true");
      filters.tag = btn.dataset.tagFilter || null;
      loadTasks();
    });
  });

  searchInput.addEventListener("input", () => {
    clearTimeout(searchDebounce);
    searchDebounce = setTimeout(() => {
      filters.q = searchInput.value.trim();
      loadTasks();
    }, 300);
  });

  if (newTaskBtn) newTaskBtn.addEventListener("click", openCreateModal);
  const cancelBtn = document.getElementById("task-cancel-btn");
  if (cancelBtn) cancelBtn.addEventListener("click", () => modal.close());

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (formError) formError.hidden = true;
    saveBtn.disabled = true;

    const id = form.elements.id.value;
    const payload = {
      title: form.elements.title.value,
      notes: form.elements.notes.value,
      tag: form.elements.tag.value,
    };
    try {
      const unchanged = id && form.elements.due_at.value === form.dataset.originalDue;
      if (!unchanged) payload.due_at = fromLocalInputValue(form.elements.due_at.value);
    } catch (err) {
      if (!(err instanceof DateInputError)) throw err;
      if (formError) {
        formError.textContent = err.message;
        formError.hidden = false;
      }
      saveBtn.disabled = false;
      form.elements.due_at.focus();
      return;
    }
    // Only present when FEATURE_ESTIMATES is on (see tasks.html).
    if (form.elements.estimate_hours) {
      const raw = form.elements.estimate_hours.value;
      payload.estimate_hours = raw === "" ? null : Number(raw);
    }

    try {
      if (id) {
        await apiFetch(`/api/tasks/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
      } else {
        await apiFetch("/api/tasks", { method: "POST", body: JSON.stringify(payload) });
      }
      modal.close();
      showToast("Task saved", "success");
      await loadTasks();
      if (newTaskBtn) newTaskBtn.focus();
    } catch (err) {
      if (formError) {
        formError.textContent = err.message;
        formError.hidden = false;
      }
    } finally {
      saveBtn.disabled = false;
    }
  });

  // Risk/start_by (I12) recompute fresh on every read, but only the page
  // that triggers a read sees that — this list left open in one tab while
  // a same-tag task completes in another doesn't otherwise learn its risk
  // badges are now stale. Re-fetching on return-to-tab is a cheap, no-infra
  // way to close that gap instead of polling on an interval.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") loadTasks();
  });

  loadTasks();
  if (openNewOnLoad) openCreateModal();
}
