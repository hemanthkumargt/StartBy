// Thin fetch wrapper shared by every page: attaches the CSRF header and
// turns the {"error": {"code","message"}} API shape into a JS Error.

function csrfToken() {
  const meta = document.querySelector('meta[name="csrf-token"]');
  return meta ? meta.content : "";
}

export async function apiFetch(path, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    "X-CSRFToken": csrfToken(),
    ...(options.headers || {}),
  };
  const response = await fetch(path, { ...options, headers, credentials: "same-origin" });

  if (response.status === 204) return null;

  let body = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }

  if (!response.ok) {
    const message = body && body.error ? body.error.message : `Request failed (${response.status})`;
    throw new Error(message);
  }
  return body;
}

const logoutBtn = document.getElementById("logout-btn");
if (logoutBtn) {
  logoutBtn.addEventListener("click", async () => {
    logoutBtn.disabled = true;
    try {
      await apiFetch("/api/auth/logout", { method: "POST" });
      window.location.href = "/login";
    } catch (err) {
      logoutBtn.disabled = false;
      alert(err.message);
    }
  });
}
