import { apiFetch } from "./api.js";
import { showToast } from "./toast.js";
import { formatDateTime, relativeTime } from "./datetime.js";
import { escapeHtml } from "./dom.js";

const ACTION_MAP = {
  completed: {
    badgeClass: "act-icon--completed",
    verb: "completed",
    icon: `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>`,
  },
  created: {
    badgeClass: "act-icon--created",
    verb: "created",
    icon: `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>`,
  },
  reopened: {
    badgeClass: "act-icon--reopened",
    verb: "reopened",
    icon: `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"></path><path d="M21 3v5h-5"></path><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"></path><path d="M8 16H3v5"></path></svg>`,
  },
  deleted: {
    badgeClass: "act-icon--deleted",
    verb: "deleted",
    icon: `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"></path><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"></path><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"></path></svg>`,
  },
  updated: {
    badgeClass: "act-icon--updated",
    verb: "updated",
    icon: `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"></path></svg>`,
  },
};

let allEntries = [];
let activeFilter = "all";

function renderEntries() {
  const activityList = document.getElementById("activity-list");
  const emptyState = document.getElementById("activity-empty");
  const counterText = document.getElementById("activity-counter-text");
  if (!activityList) return;

  const filtered = activeFilter === "all"
    ? allEntries
    : allEntries.filter((e) => {
        if (activeFilter === "updated") return e.action === "updated" || e.action === "reopened";
        return e.action === activeFilter;
      });

  if (counterText) {
    counterText.textContent = `${allEntries.length} events recorded`;
  }

  activityList.innerHTML = "";
  if (emptyState) {
    emptyState.hidden = filtered.length > 0;
  }

  for (const entry of filtered) {
    const config = ACTION_MAP[entry.action] || ACTION_MAP.updated;
    const title = entry.task_title || "a task";

    let detailHtml = "";
    if (entry.action === "updated") {
      if (entry.field === "title") {
        detailHtml = `<div class="act-diff">Renamed: <span class="act-diff__old">"${escapeHtml(entry.old_value)}"</span> <span class="act-diff__arrow">→</span> <span class="act-diff__new">"${escapeHtml(entry.new_value)}"</span></div>`;
      } else if (entry.field === "due_at") {
        const oldText = entry.old_value ? formatDateTime(entry.old_value) : "no deadline";
        const newText = entry.new_value ? formatDateTime(entry.new_value) : "no deadline";
        detailHtml = `<div class="act-diff">Deadline: <span class="act-diff__old">${escapeHtml(oldText)}</span> <span class="act-diff__arrow">→</span> <span class="act-diff__new">${escapeHtml(newText)}</span></div>`;
      }
    }

    const li = document.createElement("li");
    li.className = "act-item";
    li.innerHTML = `
      <div class="act-item__icon-wrap">
        <div class="act-item__icon ${config.badgeClass}">${config.icon}</div>
      </div>
      <div class="act-item__main">
        <div class="act-item__headline">
          <span class="act-item__actor">You</span>
          <span class="act-item__verb act-item__verb--${entry.action}">${config.verb}</span>
          <span class="act-item__target">"${escapeHtml(title)}"</span>
        </div>
        ${detailHtml}
      </div>
      <time class="act-item__time" datetime="${escapeHtml(entry.at)}" title="${escapeHtml(formatDateTime(entry.at))}">
        ${escapeHtml(relativeTime(entry.at))}
      </time>
    `;
    activityList.appendChild(li);
  }
}

// Setup Filter Buttons
const tabButtons = document.querySelectorAll("[data-filter]");
tabButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    tabButtons.forEach((b) => b.classList.remove("is-active"));
    btn.classList.add("is-active");
    activeFilter = btn.dataset.filter;
    renderEntries();
  });
});

(async () => {
  try {
    allEntries = await apiFetch("/api/activity");
    renderEntries();
  } catch (err) {
    showToast(err.message, "error");
  }
})();
