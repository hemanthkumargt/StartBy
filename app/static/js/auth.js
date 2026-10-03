import { apiFetch } from "./api.js";
import { showToast } from "./toast.js";

// ============================================================
// Form Handling (Login & Register)
// ============================================================

function wireForm(formId, path) {
  const form = document.getElementById(formId);
  if (!form) return;

  const errorEl = document.getElementById("form-error");
  const errorTextEl = errorEl ? (errorEl.querySelector(".error-text") || errorEl) : null;
  const submitBtn = form.querySelector("button[type=submit]");
  const originalBtnHtml = submitBtn ? submitBtn.innerHTML : "";

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (errorEl) errorEl.hidden = true;
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.innerHTML = `<span class="btn-spinner"></span> <span>Please wait...</span>`;
    }

    const data = Object.fromEntries(new FormData(form).entries());
    try {
      await apiFetch(path, { method: "POST", body: JSON.stringify(data) });
      window.location.href = "/";
    } catch (err) {
      if (errorTextEl) {
        errorTextEl.textContent = err.message || "An error occurred during authentication";
      }
      if (errorEl) errorEl.hidden = false;
    } finally {
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.innerHTML = originalBtnHtml;
      }
    }
  });
}

wireForm("register-form", "/api/auth/register");
wireForm("login-form", "/api/auth/login");

// ============================================================
// Password Toggle (Show / Hide)
// ============================================================

const togglePasswordBtn = document.getElementById("toggle-password-btn");
if (togglePasswordBtn) {
  togglePasswordBtn.addEventListener("click", () => {
    const passwordInput = document.getElementById("password");
    if (!passwordInput) return;

    const isPassword = passwordInput.getAttribute("type") === "password";
    passwordInput.setAttribute("type", isPassword ? "text" : "password");

    const eyeOpen = togglePasswordBtn.querySelector(".eye-open");
    const eyeClosed = togglePasswordBtn.querySelector(".eye-closed");
    if (eyeOpen && eyeClosed) {
      eyeOpen.style.display = isPassword ? "none" : "block";
      eyeClosed.style.display = isPassword ? "block" : "none";
    }
  });
}

// ============================================================
// Register Password Strength & Validation Indicator
// ============================================================

const registerPasswordInput = document.querySelector("#register-form #password");
const passwordReqHelper = document.getElementById("password-requirements");
if (registerPasswordInput && passwordReqHelper) {
  registerPasswordInput.addEventListener("input", (e) => {
    const val = e.target.value;
    if (val.length >= 8) {
      passwordReqHelper.classList.add("valid");
    } else {
      passwordReqHelper.classList.remove("valid");
    }
  });
}

// ============================================================
// 1-Click Demo Credentials Auto-Fill
// ============================================================

const demoFillBtn = document.getElementById("demo-fill-btn");
if (demoFillBtn) {
  demoFillBtn.addEventListener("click", () => {
    const emailInput = document.getElementById("email");
    const passwordInput = document.getElementById("password");

    if (emailInput && passwordInput) {
      emailInput.value = "demo@startby.local";
      passwordInput.value = "change-me";

      // Visual feedback flash
      [emailInput, passwordInput].forEach((input) => {
        input.style.transition = "background-color 0.4s ease, border-color 0.4s ease";
        input.style.backgroundColor = "rgba(59, 130, 246, 0.15)";
        input.style.borderColor = "var(--color-primary)";
        setTimeout(() => {
          input.style.backgroundColor = "";
          input.style.borderColor = "";
        }, 600);
      });

      showToast("Demo credentials filled! Click 'Sign in' to continue.", "info");
    }
  });
}

// Theme switching is handled globally by theme.js across all pages


// ============================================================
// Forgot Password Dialog
// ============================================================

const forgotPasswordLink = document.getElementById("forgot-password-link");
if (forgotPasswordLink) {
  forgotPasswordLink.addEventListener("click", (e) => {
    e.preventDefault();
    showToast(
      "Demo Environment: To reset password, use `python scripts/seed.py --reset` or register a new account.",
      "info"
    );
  });
}

// ============================================================
// Social Sign-In Modals (Google & GitHub)
// ============================================================

const oauthBackdrop = document.getElementById("oauth-modal-backdrop");
const oauthCloseBtn = document.getElementById("oauth-modal-close");
const googleLoginBtn = document.getElementById("google-login-btn");
const githubLoginBtn = document.getElementById("github-login-btn");
const oauthProviderLogo = document.getElementById("oauth-provider-logo");
const oauthModalTitle = document.getElementById("oauth-modal-title");
const oauthAccountList = document.getElementById("oauth-account-list");
const oauthCustomForm = document.getElementById("oauth-custom-form");
const oauthCustomEmail = document.getElementById("oauth-custom-email");

let currentProvider = "google";

const GOOGLE_SVG = `
  <svg width="32" height="32" viewBox="0 0 24 24">
    <path fill="#4285F4" d="M23.745 12.27c0-.7-.06-1.4-.19-2.07H12v4.51h6.6c-.29 1.52-1.14 2.8-2.4 3.66v3.05h3.88c2.27-2.09 3.66-5.17 3.66-9.15z"/>
    <path fill="#34A853" d="M12 24c3.24 0 5.95-1.08 7.93-2.91l-3.88-3.05c-1.08.72-2.45 1.16-4.05 1.16-3.12 0-5.77-2.1-6.72-4.93H1.27v3.15C3.26 21.36 7.34 24 12 24z"/>
    <path fill="#FBBC05" d="M5.28 14.27c-.25-.72-.38-1.49-.38-2.27s.13-1.55.38-2.27V6.58H1.27C.46 8.2 0 10.04 0 12s.46 3.8 1.27 5.42l4.01-3.15z"/>
    <path fill="#EA4335" d="M12 4.75c1.77 0 3.35.61 4.6 1.8l3.42-3.42C17.95 1.19 15.24 0 12 0 7.34 0 3.26 2.64 1.27 6.58l4.01 3.15c.95-2.83 3.6-4.98 6.72-4.98z"/>
  </svg>
`;

const GITHUB_SVG = `
  <svg width="32" height="32" viewBox="0 0 24 24" fill="currentColor">
    <path fill-rule="evenodd" clip-rule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.53 1.032 1.53 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z"/>
  </svg>
`;

const DEMO_ACCOUNTS = {
  google: [
    {
      name: "Cognizant Hackathon Evaluator",
      email: "evaluator.judge@gmail.com",
      badge: "Evaluator",
      avatarBg: "#4285F4",
    },
    {
      name: "Alex Morgan",
      email: "alex.google@startby.demo",
      badge: "Verified",
      avatarBg: "#34A853",
    },
  ],
  github: [
    {
      name: "Octocat Developer",
      email: "octocat@github.demo",
      badge: "GitHub Pro",
      avatarBg: "#24292e",
    },
    {
      name: "NPN Student Team",
      email: "npn.hackathon@github.demo",
      badge: "Member",
      avatarBg: "#6e5494",
    },
  ],
};

function openOAuthModal(provider) {
  if (!oauthBackdrop) return;
  currentProvider = provider;

  const isGoogle = provider === "google";
  if (oauthProviderLogo) {
    oauthProviderLogo.innerHTML = isGoogle ? GOOGLE_SVG : GITHUB_SVG;
  }
  if (oauthModalTitle) {
    oauthModalTitle.textContent = isGoogle ? "Sign in with Google" : "Authorize with GitHub";
  }

  // Render pre-configured accounts
  const accounts = DEMO_ACCOUNTS[provider] || [];
  if (oauthAccountList) {
    oauthAccountList.innerHTML = accounts
      .map(
        (acc) => `
      <div class="oauth-account-card" data-email="${acc.email}" data-name="${acc.name}">
        <div class="oauth-avatar" style="background: ${acc.avatarBg}">
          ${acc.name.charAt(0).toUpperCase()}
        </div>
        <div class="oauth-info">
          <p class="oauth-name">${acc.name}</p>
          <p class="oauth-email">${acc.email}</p>
        </div>
        <span class="oauth-badge-tag">${acc.badge}</span>
      </div>
    `
      )
      .join("");

    // Wire clicks on accounts
    oauthAccountList.querySelectorAll(".oauth-account-card").forEach((card) => {
      card.addEventListener("click", () => {
        const email = card.dataset.email;
        const name = card.dataset.name;
        performSocialAuth(currentProvider, email, name);
      });
    });
  }

  oauthBackdrop.classList.add("is-open");
  oauthBackdrop.setAttribute("aria-hidden", "false");
}

function closeOAuthModal() {
  if (!oauthBackdrop) return;
  oauthBackdrop.classList.remove("is-open");
  oauthBackdrop.setAttribute("aria-hidden", "true");
}

async function performSocialAuth(provider, email, name) {
  try {
    if (oauthAccountList) {
      oauthAccountList.innerHTML = `
        <div style="padding: 2rem; text-align: center;">
          <div class="btn-spinner" style="margin: 0 auto 1rem; width: 28px; height: 28px; border-color: var(--color-primary); border-top-color: transparent;"></div>
          <p style="font-weight: 600; color: var(--color-text);">Authenticating with ${provider.toUpperCase()}...</p>
        </div>
      `;
    }

    await apiFetch("/api/auth/social", {
      method: "POST",
      body: JSON.stringify({ provider, email, name }),
    });

    window.location.href = "/";
  } catch (err) {
    closeOAuthModal();
    showToast(err.message || "Failed to authenticate via " + provider, "error");
  }
}

if (googleLoginBtn) {
  googleLoginBtn.addEventListener("click", () => openOAuthModal("google"));
}

if (githubLoginBtn) {
  githubLoginBtn.addEventListener("click", () => openOAuthModal("github"));
}

if (oauthCloseBtn) {
  oauthCloseBtn.addEventListener("click", closeOAuthModal);
}

if (oauthBackdrop) {
  oauthBackdrop.addEventListener("click", (e) => {
    if (e.target === oauthBackdrop) closeOAuthModal();
  });
  window.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && oauthBackdrop.classList.contains("is-open")) {
      closeOAuthModal();
    }
  });
}

if (oauthCustomForm) {
  oauthCustomForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const email = oauthCustomEmail ? oauthCustomEmail.value.trim() : "";
    if (email) {
      performSocialAuth(currentProvider, email, email.split("@")[0]);
    }
  });
}
