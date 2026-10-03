import { apiFetch } from "./api.js";
import { showToast } from "./toast.js";
import { setDarkMode } from "./theme.js";

const form = document.getElementById("settings-form");
if (form) {
  const errorEl = document.getElementById("settings-error");
  const submitBtn = form.querySelector("button[type=submit]");
  const darkModeCheckbox = document.getElementById("dark-mode-checkbox");

  if (darkModeCheckbox) {
    darkModeCheckbox.addEventListener("change", async () => {
      try {
        await setDarkMode(darkModeCheckbox.checked);
      } catch (err) {
        showToast(err.message, "error");
      }
    });
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (errorEl) errorEl.hidden = true;
    if (submitBtn) submitBtn.disabled = true;

    const isDark = form.elements.dark_mode.checked;
    try {
      await setDarkMode(isDark);
      await apiFetch("/api/me", {
        method: "PATCH",
        body: JSON.stringify({ timezone: form.elements.timezone.value }),
      });
      showToast("Settings saved successfully", "success");
    } catch (err) {
      if (errorEl) {
        errorEl.textContent = err.message;
        errorEl.hidden = false;
      }
    } finally {
      if (submitBtn) submitBtn.disabled = false;
    }
  });
}
