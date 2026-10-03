import { apiFetch } from "./api.js";
import { showToast } from "./toast.js";
import { formatDateTime, fromLocalInputValue, toLocalInputValue } from "./datetime.js";
import { escapeHtml } from "./dom.js";

// Lucide-style SVG vector icons
const ICONS = {
  zap: `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg>`,
  check: `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>`,
  clock: `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>`,
  tag: `<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"></path><line x1="7" y1="7" x2="7.01" y2="7"></line></svg>`,
  pencil: `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"></path></svg>`,
  trash: `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"></path><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"></path><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"></path></svg>`,
};

// Unified task card renderer for both Tasks page and Dashboard priority radar
export function renderTaskCard(task, handlers = {}) {
  const card = document.createElement(handlers.onToggle ? "li" : "div");
  card.className = "task-card";

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
        </div>
      </div>
    </div>
    ${handlers.onEdit || handlers.onDelete
      ? `<div class="task-card__actions">
             ${handlers.onEdit ? `<button type="button" class="task-card__edit">${ICONS.pencil} <span>Edit</span></button>` : ""}
             ${handlers.onDelete ? `<button type="button" class="task-card__delete">${ICONS.trash} <span>Delete</span></button>` : ""}
           </div>`
      : ""
    }
  `;

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
    modalTitle.textContent = "Edit Task";
    form.elements.id.value = task.id;
    form.elements.title.value = task.title;
    form.elements.notes.value = task.notes || "";
    form.elements.tag.value = task.tag;
    form.elements.due_at.value = toLocalInputValue(task.due_at);
    if (formError) formError.hidden = true;
    modal.showModal();
    form.elements.title.focus();
  }

  function openCreateModal() {
    modalTitle.textContent = "New Task";
    form.reset();
    form.elements.id.value = "";
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
      due_at: fromLocalInputValue(form.elements.due_at.value),
    };

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

  loadTasks();
}
