import { apiFetch } from "./api.js";
import { showToast } from "./toast.js";

const THEME_KEYS = ["startby-theme"];

export function getStoredTheme() {
  try {
    for (const key of THEME_KEYS) {
      const val = localStorage.getItem(key);
      if (val === "light" || val === "dark") return val;
    }
  } catch (_) {}
  return document.documentElement.dataset.theme === "light" ? "light" : "dark"; // what the server rendered
}

export function updateThemeUI(theme) {
  const isDark = theme === "dark";

  // 1. Toggle sun/moon icons
  const moonIcons = document.querySelectorAll(
    ".theme-icon-svg--moon, .theme-svg--moon, [data-theme-icon='moon']"
  );
  const sunIcons = document.querySelectorAll(
    ".theme-icon-svg--sun, .theme-svg--sun, [data-theme-icon='sun']"
  );

  moonIcons.forEach((el) => {
    el.style.display = isDark ? "none" : "inline-block";
  });
  sunIcons.forEach((el) => {
    el.style.display = isDark ? "inline-block" : "none";
  });

  // 2. Toggle text labels ("Light" vs "Dark")
  const labels = document.querySelectorAll(".theme-label, [data-theme-label]");
  labels.forEach((el) => {
    el.textContent = isDark ? "Light" : "Dark";
  });

  // 3. Sync Settings checkbox if present
  const darkModeCheckbox = document.getElementById("dark-mode-checkbox");
  if (darkModeCheckbox && darkModeCheckbox.checked !== isDark) {
    darkModeCheckbox.checked = isDark;
  }
}

export async function applyTheme(theme, persistToDb = true) {
  const normalized = theme === "light" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", normalized);
  document.documentElement.dataset.theme = normalized;

  // Persist locally
  try {
    for (const key of THEME_KEYS) {
      localStorage.setItem(key, normalized);
    }
    // Set cookie for SSR
    document.cookie = `startby-theme=${normalized}; path=/; max-age=31536000; SameSite=Lax`;
  } catch (_) {}

  // Update all UI elements
  updateThemeUI(normalized);

  // Persist to user record in DB if authenticated
  if (persistToDb) {
    const isDark = normalized === "dark";
    try {
      const hasCsrf = document.querySelector('meta[name="csrf-token"]');
      const isAuthPage =
        window.location.pathname.startsWith("/login") ||
        window.location.pathname.startsWith("/register");
      if (hasCsrf && !isAuthPage) {
        await apiFetch("/api/me", {
          method: "PATCH",
          body: JSON.stringify({ dark_mode: isDark }),
        });
      }
    } catch (_) {
      // Silently ignore if unauthenticated or offline
    }
  }
}

export async function setDarkMode(isDark) {
  await applyTheme(isDark ? "dark" : "light", true);
}

// Global real-time listener for cross-tab or cross-window theme changes
window.addEventListener("storage", (event) => {
  if (THEME_KEYS.includes(event.key) && (event.newValue === "light" || event.newValue === "dark")) {
    applyTheme(event.newValue, false);
  }
});

// Initialize on DOM load
function initTheme() {
  const current = getStoredTheme();
  applyTheme(current, false);

  const toggleButtons = [
    document.getElementById("theme-toggle-btn"),
    document.getElementById("theme-toggle-btn-mobile"),
    document.getElementById("auth-theme-toggle"),
    ...document.querySelectorAll(".theme-switch-btn, [data-theme-toggle]"),
  ].filter(Boolean);

  toggleButtons.forEach((btn) => {
    if (btn._hasThemeListener) return;
    btn._hasThemeListener = true;

    btn.addEventListener("click", async (e) => {
      e.preventDefault();
      const currentTheme = document.documentElement.dataset.theme === "dark" ? "dark" : "light";
      const nextTheme = currentTheme === "dark" ? "light" : "dark";
      btn.disabled = true;
      try {
        await applyTheme(nextTheme, true);
      } catch (err) {
        showToast(err.message, "error");
      } finally {
        btn.disabled = false;
      }
    });
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initTheme);
} else {
  initTheme();
}
