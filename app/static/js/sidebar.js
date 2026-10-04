// "Today" card in the sidebar: three numbers from the dashboard API, so the
// sidebar is useful on every page instead of just a list of links.
import { apiFetch } from "./api.js";

const card = document.getElementById("sidebar-today");

function setCount(key, value) {
  const el = card.querySelector(`[data-count="${key}"]`);
  if (el) el.textContent = String(value);
}

async function load() {
  try {
    const data = await apiFetch("/api/dashboard");
    setCount("pending", data.pending ?? 0);
    setCount("overdue", data.overdue ?? 0);
    setCount("completed", data.completed ?? 0);
    card.classList.toggle("has-overdue", (data.overdue ?? 0) > 0);
  } catch {
    card.hidden = true; // never show a broken card
  }
}

if (card) {
  load();
  // Refresh when the tab is shown again, so the numbers do not go stale.
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) load();
  });
}
