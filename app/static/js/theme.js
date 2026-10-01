import { apiFetch } from "./api.js";
import { showToast } from "./toast.js";

// Persists to the user record (PATCH /api/me) and applies immediately —
// the page itself is already rendered server-side with the right theme
// (base.html sets <html data-theme>), so there is never a flash on load;
// this only handles the *next* toggle, in this tab, without a reload.
export async function setDarkMode(isDark) {
  await apiFetch("/api/me", { method: "PATCH", body: JSON.stringify({ dark_mode: isDark }) });
  document.documentElement.dataset.theme = isDark ? "dark" : "light";
}

const headerToggle = document.getElementById("theme-toggle-btn");
if (headerToggle) {
  headerToggle.addEventListener("click", async () => {
    const goingDark = document.documentElement.dataset.theme !== "dark";
    headerToggle.disabled = true;
    try {
      await setDarkMode(goingDark);
      headerToggle.textContent = goingDark ? "☀️" : "🌙";
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      headerToggle.disabled = false;
    }
  });
}
