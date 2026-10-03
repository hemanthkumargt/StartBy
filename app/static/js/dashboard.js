import { apiFetch } from "./api.js";
import { showToast } from "./toast.js";
import { renderTaskCard } from "./tasks.js";
import { fromLocalInputValue } from "./datetime.js";

const countEls = {
  total: document.getElementById("count-total"),
  pending: document.getElementById("count-pending"),
  completed: document.getElementById("count-completed"),
  overdue: document.getElementById("count-overdue"),
};

function updateGreeting() {
  const prefixEl = document.getElementById("dashboard-greeting-prefix");
  if (!prefixEl) return;

  const hour = new Date().getHours();
  let timeOfDay = "Good morning";
  if (hour >= 12 && hour < 17) {
    timeOfDay = "Good afternoon";
  } else if (hour >= 17) {
    timeOfDay = "Good evening";
  }
  prefixEl.textContent = timeOfDay;
}

async function loadDashboard() {
  const dueNextList = document.getElementById("due-next-list");
  const dueNextEmpty = document.getElementById("due-next-empty");
  if (!dueNextList) return;

  try {
    const data = await apiFetch("/api/dashboard");
    if (countEls.total) countEls.total.textContent = data.total;
    if (countEls.pending) countEls.pending.textContent = data.pending;
    if (countEls.completed) countEls.completed.textContent = data.completed;
    if (countEls.overdue) countEls.overdue.textContent = data.overdue;

    dueNextList.innerHTML = "";
    if (dueNextEmpty) dueNextEmpty.hidden = data.due_next.length > 0;
    for (const task of data.due_next) {
      dueNextList.appendChild(renderTaskCard(task));
    }
  } catch (err) {
    showToast(err.message, "error");
  }
}

const quickAddForm = document.getElementById("quick-add-form");
if (quickAddForm) {
  const errorEl = document.getElementById("quick-add-error");
  const submitBtn = quickAddForm.querySelector("button[type=submit]");

  quickAddForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (errorEl) errorEl.hidden = true;
    if (submitBtn) submitBtn.disabled = true;

    const payload = {
      title: quickAddForm.elements.title.value,
      tag: quickAddForm.elements.tag.value,
      due_at: fromLocalInputValue(quickAddForm.elements.due_at.value),
    };

    try {
      await apiFetch("/api/tasks", { method: "POST", body: JSON.stringify(payload) });
      quickAddForm.reset();
      showToast("Task added to workspace", "success");
      await loadDashboard();
    } catch (err) {
      if (errorEl) {
        errorEl.textContent = err.message;
        errorEl.hidden = false;
      }
    } finally {
      if (submitBtn) submitBtn.disabled = false;
    }
  });

  updateGreeting();
  loadDashboard();
}
