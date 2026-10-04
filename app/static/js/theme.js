import { apiFetch } from "./api.js";
import { showToast } from "./toast.js";

// Persists to the user record (PATCH /api/me) and applies immediately
export async function setDarkMode(isDark) {
  await apiFetch("/api/me", { method: "PATCH", body: JSON.stringify({ dark_mode: isDark }) });
  document.documentElement.dataset.theme = isDark ? "dark" : "light";
  updateThemeIcons(isDark);
  // Keep the Settings switch honest when the header toggle changes the theme.
  const settingsSwitch = document.getElementById("dark-mode-checkbox");
  if (settingsSwitch) settingsSwitch.checked = isDark;
}

function updateThemeIcons(isDark) {
  const moonIcons = document.querySelectorAll(".theme-icon-svg--moon");
  const sunIcons = document.querySelectorAll(".theme-icon-svg--sun");

  moonIcons.forEach((icon) => {
    icon.style.display = isDark ? "none" : "block";
  });
  sunIcons.forEach((icon) => {
    icon.style.display = isDark ? "block" : "none";
  });
}

const toggles = [
  document.getElementById("theme-toggle-btn"),
  document.getElementById("theme-toggle-btn-mobile"),
].filter(Boolean);

toggles.forEach((btn) => {
  btn.addEventListener("click", async () => {
    const goingDark = document.documentElement.dataset.theme !== "dark";
    btn.disabled = true;
    try {
      await setDarkMode(goingDark);
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      btn.disabled = false;
    }
  });
});
