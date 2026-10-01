import { apiFetch } from "./api.js";

function wireForm(formId, path) {
  const form = document.getElementById(formId);
  if (!form) return;

  const errorEl = document.getElementById("form-error");
  const submitBtn = form.querySelector("button[type=submit]");

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    errorEl.hidden = true;
    submitBtn.disabled = true;

    const data = Object.fromEntries(new FormData(form).entries());
    try {
      await apiFetch(path, { method: "POST", body: JSON.stringify(data) });
      window.location.href = "/";
    } catch (err) {
      errorEl.textContent = err.message;
      errorEl.hidden = false;
    } finally {
      submitBtn.disabled = false;
    }
  });
}

wireForm("register-form", "/api/auth/register");
wireForm("login-form", "/api/auth/login");
