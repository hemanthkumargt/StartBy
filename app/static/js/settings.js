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

    try {
      // Theme saves the moment the switch is flipped; only the timezone needs
      // Save. (Sending dark_mode here too used to undo a theme changed from the
      // header toggle, because the switch had not been told about it.)
      await apiFetch("/api/me", {
        method: "PATCH",
        body: JSON.stringify({
          timezone: form.elements.timezone.value,
          // Only sent when the voice assistant card exists; blank clears the custom name.
          ...(form.elements.assistant_name ? { assistant_name: form.elements.assistant_name.value } : {}),
        }),
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

// Google Calendar card (only rendered when the server has OAuth configured).
const calendarStatus = document.getElementById("calendar-status");
if (calendarStatus) {
  const connectLink = document.getElementById("calendar-connect");
  const disconnectBtn = document.getElementById("calendar-disconnect");

  function showCalendar(connected) {
    calendarStatus.textContent = connected
      ? "Connected — your tasks are mirrored to your calendar."
      : "Not connected.";
    connectLink.hidden = connected;
    disconnectBtn.hidden = !connected;
  }

  const flash = new URLSearchParams(window.location.search).get("calendar");
  if (flash === "denied") showToast("Calendar access was not granted", "error");
  if (flash === "error") showToast("Could not connect Google Calendar — try again", "error");
  if (flash === "connected") showToast("Google Calendar connected", "success");

  apiFetch("/api/calendar/status")
    .then((status) => showCalendar(status.connected))
    .catch((err) => {
      calendarStatus.textContent = "Could not check the connection.";
      showToast(err.message, "error");
    });

  disconnectBtn.addEventListener("click", async () => {
    if (!confirm("Disconnect Google Calendar? Events Cloud 6 added will be removed from it.")) return;
    disconnectBtn.disabled = true;
    try {
      await apiFetch("/api/calendar/disconnect", { method: "POST" });
      showCalendar(false);
      showToast("Google Calendar disconnected", "success");
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      disconnectBtn.disabled = false;
    }
  });
}
