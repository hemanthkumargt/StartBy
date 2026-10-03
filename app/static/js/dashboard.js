import { apiFetch } from "./api.js";
import { showToast } from "./toast.js";
import { renderTaskCard, toggleComplete } from "./tasks.js";
import { fromLocalInputValue } from "./datetime.js";

const countEls = {
  total: document.getElementById("count-total"),
  pending: document.getElementById("count-pending"),
  completed: document.getElementById("count-completed"),
  overdue: document.getElementById("count-overdue"),
};

// Quick-add submit and the "Do this now" card's complete/reopen toggle can
// each trigger a loadDashboard() while an earlier one is still in flight —
// same sequence guard as tasks.js's loadTasks(), so a slower earlier
// response can't land after a faster later one and overwrite the page with
// stale counts or a stale "do this now" card.
let loadSeq = 0;

async function loadDashboard() {
  const dueNextList = document.getElementById("due-next-list");
  const dueNextEmpty = document.getElementById("due-next-empty");
  if (!dueNextList) return;

  // #do-this-now only exists in the DOM when FEATURE_ESTIMATES is on (see
  // home.html's {% if feature_flags.estimates %}) — its presence is the
  // gate here, since the API only sends do_this_now under the same flag.
  const doThisNowSection = document.getElementById("do-this-now");
  const doThisNowCard = document.getElementById("do-this-now-card");

  const seq = ++loadSeq;
  try {
    const data = await apiFetch("/api/dashboard");
    if (seq !== loadSeq) return;
    countEls.total.textContent = data.total;
    countEls.pending.textContent = data.pending;
    countEls.completed.textContent = data.completed;
    countEls.overdue.textContent = data.overdue;

    dueNextList.innerHTML = "";
    dueNextEmpty.hidden = data.due_next.length > 0;
    for (const task of data.due_next) {
      dueNextList.appendChild(renderTaskCard(task));
    }

    if (doThisNowSection) {
      doThisNowCard.innerHTML = "";
      if (data.do_this_now) {
        doThisNowCard.appendChild(
          renderTaskCard(data.do_this_now, { onToggle: (t) => toggleComplete(t, loadDashboard) })
        );
      }
      doThisNowSection.hidden = !data.do_this_now;
    }
  } catch (err) {
    if (seq !== loadSeq) return;
    showToast(err.message, "error");
  }
}

const quickAddForm = document.getElementById("quick-add-form");
if (quickAddForm) {
  const errorEl = document.getElementById("quick-add-error");
  const submitBtn = quickAddForm.querySelector("button[type=submit]");

  quickAddForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    errorEl.hidden = true;
    submitBtn.disabled = true;

    const payload = {
      title: quickAddForm.elements.title.value,
      tag: quickAddForm.elements.tag.value,
      due_at: fromLocalInputValue(quickAddForm.elements.due_at.value),
    };

    try {
      await apiFetch("/api/tasks", { method: "POST", body: JSON.stringify(payload) });
      quickAddForm.reset();
      showToast("Task added", "success");
      await loadDashboard();
    } catch (err) {
      errorEl.textContent = err.message;
      errorEl.hidden = false;
    } finally {
      submitBtn.disabled = false;
    }
  });

  // Risk/start_by (I12) recompute fresh on every read, but only the page
  // that triggers a read sees that — a dashboard left open in one tab
  // while a same-tag task is completed in another doesn't otherwise learn
  // its "Do this now" card or risk badges are now stale. Re-fetching on
  // return-to-tab is a cheap, no-infra way to close that gap instead of
  // polling on an interval.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") loadDashboard();
  });

  loadDashboard();
}
