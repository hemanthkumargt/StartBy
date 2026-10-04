import { apiFetch } from "./api.js";
import { showToast } from "./toast.js";
import { renderTaskCard, toggleComplete } from "./tasks.js";
import { DateInputError, fromLocalInputValue } from "./datetime.js";

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

function updateGreeting() {
  const prefixEl = document.getElementById("dashboard-greeting-prefix");
  if (!prefixEl) return;

  const meta = document.querySelector('meta[name="user-timezone"]');
  let hour = new Date().getHours();
  try {
    if (meta && meta.content) {
      hour = Number(
        new Intl.DateTimeFormat("en-GB", {
          hour: "2-digit",
          hourCycle: "h23",
          timeZone: meta.content,
        }).format(new Date())
      );
    }
  } catch {
    // unknown zone in this browser: keep the browser's own hour
  }
  let timeOfDay = "Good morning";
  if (hour >= 12 && hour < 17) {
    timeOfDay = "Good afternoon";
  } else if (hour >= 17) {
    timeOfDay = "Good evening";
  }
  prefixEl.textContent = timeOfDay;
}

// The overload banner only exists in the DOM when FEATURE_INSIGHTS is on
// (see home.html); a failure here must never break the rest of the
// dashboard, so it has its own error handling and stays silent.
async function loadOverloadBanner() {
  const banner = document.getElementById("overload-banner");
  if (!banner) return;
  try {
    const { overload } = await apiFetch("/api/insights");
    banner.hidden = overload.level === "none";
    banner.dataset.level = overload.level;
    document.getElementById("overload-banner-text").textContent = overload.message;
  } catch {
    banner.hidden = true;
  }
}

const TAGS = ["study", "work", "personal"];

// Completion widget + shortcut counts, computed from the user's real tasks —
// these used to be static placeholders ("0%", "Steady Progress") that never
// changed, which read as real data. On failure they stay as dashes.
let progressSeq = 0;
async function loadProgress() {
  const pctText = document.getElementById("velocity-pct-text");
  if (!pctText) return;
  const seq = ++progressSeq;
  try {
    const tasks = await apiFetch("/api/tasks");
    if (seq !== progressSeq) return; // a newer load is in flight; this one is stale
    const pct = (done, total) => (total === 0 ? 0 : Math.round((done / total) * 100));
    const done = tasks.filter((t) => t.status === "done").length;
    const overall = pct(done, tasks.length);
    pctText.textContent = tasks.length === 0 ? "—" : `${overall}%`;
    document.getElementById("velocity-fill-bar").style.width = `${overall}%`;

    for (const tag of TAGS) {
      const inTag = tasks.filter((t) => t.tag === tag);
      const doneInTag = inTag.filter((t) => t.status === "done").length;
      document.getElementById(`stat-${tag}-ratio`).textContent = `${doneInTag} of ${inTag.length} done`;
      document.getElementById(`mini-bar-${tag}`).style.width = `${pct(doneInTag, inTag.length)}%`;
    }

    const badge = document.getElementById("momentum-badge");
    const overdue = tasks.filter((t) => t.status === "pending" && t.is_overdue).length;
    badge.classList.remove("momentum-tag--warning", "momentum-tag--high");
    if (tasks.length === 0) {
      badge.textContent = "No tasks yet";
    } else if (overdue > 0) {
      badge.textContent = `${overdue} overdue`;
      badge.classList.add("momentum-tag--warning");
    } else if (overall >= 70) {
      badge.textContent = "Strong progress";
      badge.classList.add("momentum-tag--high");
    } else {
      badge.textContent = `${overall}% done`;
    }

    const pending = tasks.length - done;
    const shortcut = document.getElementById("shortcut-pending-count");
    if (shortcut) shortcut.textContent = `${pending} active ${pending === 1 ? "task" : "tasks"}`;
  } catch {
    // The main dashboard load already reports API failures; keep the dashes.
  }
}

function showTodayDate() {
  const el = document.getElementById("dashboard-live-date");
  if (!el) return;
  const meta = document.querySelector('meta[name="user-timezone"]');
  el.textContent = new Date().toLocaleDateString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
    timeZone: meta && meta.content ? meta.content : undefined,
  });
}

async function loadDashboard() {
  loadOverloadBanner();
  loadProgress();
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
    if (countEls.total) countEls.total.textContent = data.total;
    if (countEls.pending) countEls.pending.textContent = data.pending;
    if (countEls.completed) countEls.completed.textContent = data.completed;
    if (countEls.overdue) countEls.overdue.textContent = data.overdue;

    dueNextList.innerHTML = "";
    if (dueNextEmpty) dueNextEmpty.hidden = data.due_next.length > 0;
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
    if (errorEl) errorEl.hidden = true;
    if (submitBtn) submitBtn.disabled = true;

    const payload = {
      title: quickAddForm.elements.title.value,
      tag: quickAddForm.elements.tag.value,
    };
    try {
      payload.due_at = fromLocalInputValue(quickAddForm.elements.due_at.value);
    } catch (err) {
      if (!(err instanceof DateInputError)) throw err;
      if (errorEl) {
        errorEl.textContent = err.message;
        errorEl.hidden = false;
      }
      if (submitBtn) submitBtn.disabled = false;
      return;
    }

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

  // Risk/start_by (I12) recompute fresh on every read, but only the page
  // that triggers a read sees that — a dashboard left open in one tab
  // while a same-tag task is completed in another doesn't otherwise learn
  // its "Do this now" card or risk badges are now stale. Re-fetching on
  // return-to-tab is a cheap, no-infra way to close that gap instead of
  // polling on an interval.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") loadDashboard();
  });


  updateGreeting();
  showTodayDate();
  loadDashboard();
}
