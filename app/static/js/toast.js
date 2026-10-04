// Long enough to read a sentence; errors stay longer, and are announced as alerts
// (the container is a polite live region, which screen readers may skip over).
const DISMISS_AFTER_MS = 6000;
const ERROR_DISMISS_AFTER_MS = 10000;

export function showToast(message, type = "error") {
  const container = document.getElementById("toast-container");
  if (!container) return;

  const toast = document.createElement("div");
  toast.className = `toast toast--${type}`;
  toast.textContent = message;
  if (type === "error") toast.setAttribute("role", "alert");
  container.appendChild(toast);

  setTimeout(() => toast.remove(), type === "error" ? ERROR_DISMISS_AFTER_MS : DISMISS_AFTER_MS);
}
