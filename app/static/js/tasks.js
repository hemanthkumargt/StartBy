import { apiFetch } from "./api.js";
import { showToast } from "./toast.js";
import { formatDateTime, fromLocalInputValue, toLocalInputValue } from "./datetime.js";
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

// The one function every page uses to render a task — new badges or fields
// slot in here only (PRD extension-point rule). `handlers` is optional:
// pass none for a read-only card (e.g. the dashboard's "due next" list).
export function renderTaskCard(task, handlers = {}) {
  const card = document.createElement(handlers.onToggle ? "li" : "div");
  card.className = "task-card";

  const badgeClass =
    task.status === "done" ? "badge--done" : task.is_overdue ? "badge--overdue" : "badge--pending";
  const badgeLabel = task.status === "done" ? "Done" : task.is_overdue ? "Overdue" : "Pending";

  card.innerHTML = `
    <div class="task-card__main">
      ${
        handlers.onToggle
          ? `<input type="checkbox" class="task-card__checkbox"
               ${task.status === "done" ? "checked" : ""}
               aria-label="Mark '${escapeHtml(task.title)}' as ${task.status === "done" ? "pending" : "done"}">`
          : ""
      }
      <div class="task-card__body">
        <p class="task-card__title">${escapeHtml(task.title)}</p>
        ${task.notes ? `<p class="task-card__notes">${escapeHtml(task.notes)}</p>` : ""}
        <div class="task-card__meta">
          <span class="tag-chip tag-chip--${task.tag}">${task.tag}</span>
          <span class="badge ${badgeClass}">${badgeLabel}</span>
          ${task.due_at ? `<span class="task-card__due">${formatDateTime(task.due_at)}</span>` : ""}
          ${renderStartBy(task)}
        </div>
      </div>
    </div>
    ${
      handlers.onEdit || handlers.onDelete
        ? `<div class="task-card__actions">
             ${handlers.onEdit ? `<button type="button" class="task-card__edit">Edit</button>` : ""}
             ${handlers.onDelete ? `<button type="button" class="task-card__delete">Delete</button>` : ""}
           </div>`
        : ""
    }
  `;

  if (handlers.onToggle) {
    card.querySelector(".task-card__checkbox").addEventListener("change", (e) => {
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
function promptForActualHours(task) {
  return new Promise((resolve) => {
    const dialog = document.createElement("dialog");
    dialog.className = "task-modal";
    dialog.innerHTML = `
      <form method="dialog">
        <h2 class="actual-hours-prompt__title"></h2>
        <label for="actual-hours-input">Actual hours (optional)</label>
        <input id="actual-hours-input" type="number" step="0.25" min="0.25" max="100" placeholder="e.g. 2.5">
        <div class="modal-actions">
          <button type="submit" value="skip">Skip</button>
          <button type="submit" value="save">Save</button>
        </div>
      </form>
    `;
    dialog.querySelector(".actual-hours-prompt__title").textContent =
      `How many hours did "${task.title}" actually take?`;
    const input = dialog.querySelector("#actual-hours-input");
    const saveBtn = dialog.querySelector('button[value="save"]');

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
        resolve(
          dialog.returnValue === "save" && input.value.trim() !== "" && !Number.isNaN(hours)
            ? hours
            : undefined
        );
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
    actualHours = await promptForActualHours(task);
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

  function buildQuery() {
    const params = new URLSearchParams();
    if (filters.status) params.set("status", filters.status);
    if (filters.tag) params.set("tag", filters.tag);
    if (filters.q) params.set("q", filters.q);
    const qs = params.toString();
    return qs ? `/api/tasks?${qs}` : "/api/tasks";
  }

  function openEditModal(task) {
    modalTitle.textContent = "Edit task";
    form.elements.id.value = task.id;
    form.elements.title.value = task.title;
    form.elements.notes.value = task.notes || "";
    form.elements.tag.value = task.tag;
    form.elements.due_at.value = toLocalInputValue(task.due_at);
    // Only present when FEATURE_ESTIMATES is on (see tasks.html).
    if (form.elements.estimate_hours) {
      form.elements.estimate_hours.value = task.estimate_hours ?? "";
    }
    formError.hidden = true;
    modal.showModal();
    form.elements.title.focus();
  }

  function openCreateModal() {
    modalTitle.textContent = "New task";
    form.reset();
    form.elements.id.value = "";
    formError.hidden = true;
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

  // Tab/tag clicks and the debounced search can each fire a loadTasks()
  // while an earlier one is still in flight; without a sequence guard, a
  // slower earlier response can land after a faster later one and
  // overwrite the list with results that no longer match the active
  // filters. Each call stamps its own number and only applies its result
  // if no newer call has started since.
  let loadSeq = 0;

  async function loadTasks() {
    const seq = ++loadSeq;
    try {
      const tasks = await apiFetch(buildQuery());
      if (seq !== loadSeq) return;
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

  newTaskBtn.addEventListener("click", openCreateModal);
  document.getElementById("task-cancel-btn").addEventListener("click", () => modal.close());

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    formError.hidden = true;
    saveBtn.disabled = true;

    const id = form.elements.id.value;
    const payload = {
      title: form.elements.title.value,
      notes: form.elements.notes.value,
      tag: form.elements.tag.value,
      due_at: fromLocalInputValue(form.elements.due_at.value),
    };
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
      // loadTasks() rebuilds the whole list, destroying whatever focus
      // <dialog> just restored (the Edit button that opened it) — without
      // this, focus silently drops to <body> and a keyboard/screen-reader
      // user loses their place entirely.
      newTaskBtn.focus();
    } catch (err) {
      formError.textContent = err.message;
      formError.hidden = false;
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
}
