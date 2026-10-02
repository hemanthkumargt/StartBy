import { apiFetch } from "./api.js";
import { showToast } from "./toast.js";
import { formatDateTime, relativeTime } from "./datetime.js";
import { escapeHtml } from "./dom.js";

function describe(entry) {
  const title = entry.task_title || "a deleted task";

  if (entry.action === "created") return `Created "${title}"`;
  if (entry.action === "completed") return `Completed "${title}"`;
  if (entry.action === "reopened") return `Reopened "${title}"`;
  if (entry.action === "deleted") return `Deleted "${title}"`;

  // updated
  if (entry.field === "title") {
    return `Renamed "${entry.old_value}" to "${entry.new_value}"`;
  }
  if (entry.field === "due_at") {
    const oldText = entry.old_value ? formatDateTime(entry.old_value) : "no due date";
    const newText = entry.new_value ? formatDateTime(entry.new_value) : "no due date";
    return `Edited "${title}": due ${oldText} → ${newText}`;
  }
  return `Edited "${title}": ${entry.field} changed`;
}

const activityList = document.getElementById("activity-list");
if (activityList) {
  const emptyState = document.getElementById("activity-empty");

  (async () => {
    try {
      const entries = await apiFetch("/api/activity");
      emptyState.hidden = entries.length > 0;
      for (const entry of entries) {
        const li = document.createElement("li");
        li.className = "activity-entry";
        li.innerHTML = `
          <p class="activity-entry__text">${escapeHtml(describe(entry))}</p>
          <time class="activity-entry__time" datetime="${escapeHtml(entry.at)}">${escapeHtml(relativeTime(entry.at))}</time>
        `;
        activityList.appendChild(li);
      }
    } catch (err) {
      showToast(err.message, "error");
    }
  })();
}
