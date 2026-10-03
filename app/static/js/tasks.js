import { apiFetch } from "./api.js";
import { showToast } from "./toast.js";
import { formatDateTime, fromLocalInputValue, toLocalInputValue } from "./datetime.js";
import { escapeHtml } from "./dom.js";

// start_by/start_by_passed only exist in the payload at all when
// FEATURE_ESTIMATES is on (task_service omits both keys entirely when it's
// off) — their presence is the only check needed here, not the flag itself.
// start_by_passed is computed server-side (task_service.serialize_task, via
// timeutil) the same way is_overdue already is, so Adaptive Replanning
// (CLAUDE.md 2.5) needs no client-side time comparison or recompute step:
// a task already past its recommended start time just reads that way on the
// very next render.
function renderStartBy(task) {
  if (!("start_by" in task) || task.status !== "pending" || !task.start_by) {
    return "";
  }
  if (task.start_by_passed) {
    return `<span class="task-card__start-by task-card__start-by--now">Start now</span>`;
  }
  return `<span class="task-card__start-by">Start by ${formatDateTime(task.start_by)}</span>`;
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

  async function toggleComplete(task) {
    const path =
      task.status === "done" ? `/api/tasks/${task.id}/reopen` : `/api/tasks/${task.id}/complete`;
    try {
      await apiFetch(path, { method: "POST" });
      await loadTasks();
    } catch (err) {
      showToast(err.message, "error");
    }
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
          renderTaskCard(task, { onToggle: toggleComplete, onEdit: openEditModal, onDelete: deleteTask })
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

  loadTasks();
}
