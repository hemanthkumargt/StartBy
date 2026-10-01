import { apiFetch } from "./api.js";
import { showToast } from "./toast.js";
import { setDarkMode } from "./theme.js";

const form = document.getElementById("settings-form");
if (form) {
  const errorEl = document.getElementById("settings-error");
  const headerToggle = document.getElementById("theme-toggle-btn");
  const submitBtn = form.querySelector("button[type=submit]");

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    errorEl.hidden = true;
    submitBtn.disabled = true;

    const isDark = form.elements.dark_mode.checked;
    try {
      await setDarkMode(isDark);
      await apiFetch("/api/me", {
        method: "PATCH",
        body: JSON.stringify({ timezone: form.elements.timezone.value }),
      });
      if (headerToggle) headerToggle.textContent = isDark ? "☀️" : "🌙";
      showToast("Settings saved", "success");
    } catch (err) {
      errorEl.textContent = err.message;
      errorEl.hidden = false;
    } finally {
      submitBtn.disabled = false;
    }
  });
}
