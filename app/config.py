import os
import secrets


def _flag(value: str) -> bool:
    """1/true/yes/on (any case, surrounding space ignored). Only "1" used to count,
    so BEHIND_PROXY=true or SECURE_COOKIES=yes were silently off."""
    return value.split("#", 1)[0].strip().lower() in ("1", "true", "yes", "on")


class Config:
    """Loaded from environment variables (set via .env in development)."""

    def __init__(self, env: dict[str, str] | None = None) -> None:
        env = env if env is not None else os.environ

        # No fixed fallback: a hardcoded default would be a known value
        # checked into this public repo, letting anyone forge a session
        # cookie if .env ever fails to load in production. A fresh random
        # key fails safe instead — sessions just won't survive a restart
        # until SECRET_KEY is actually set.
        self.SECRET_KEY = env.get("SECRET_KEY") or secrets.token_hex(32)
        self.DATABASE_PATH = env.get("DATABASE_PATH", "instance/app.db")
        self.DEFAULT_TIMEZONE = env.get("DEFAULT_TIMEZONE", "Asia/Kolkata")
        self.CRON_SECRET = env.get("CRON_SECRET", "")

        self.SMTP_HOST = env.get("SMTP_HOST", "smtp.gmail.com")
        self.SMTP_PORT = int(env.get("SMTP_PORT", "587"))
        self.SMTP_USER = env.get("SMTP_USER", "")
        self.SMTP_PASSWORD = env.get("SMTP_PASSWORD", "")

        self.GEMINI_API_KEY = env.get("GEMINI_API_KEY", "")
        self.GEMINI_MODEL = env.get("GEMINI_MODEL", "gemini-flash-latest")
        # "ai_studio" (API key, free tier) or "vertex" (the VM's service account).
        self.GEMINI_BACKEND = env.get("GEMINI_BACKEND", "ai_studio")
        self.GCP_PROJECT = env.get("GCP_PROJECT", "")
        self.GCP_LOCATION = env.get("GCP_LOCATION", "us-central1")

        # --- Google Cloud integrations. Each is off until its settings are
        # filled in, and every one degrades to the app's local behaviour
        # when Google is unreachable (see app/gcp/__init__.py).
        self.APP_BASE_URL = env.get("APP_BASE_URL", "").rstrip("/")
        # Google Calendar (per-user OAuth). Enabled when both are set;
        # the redirect URI defaults to APP_BASE_URL + /calendar/callback and
        # must be registered in the OAuth client (localhost or https only).
        self.GOOGLE_CLIENT_ID = env.get("GOOGLE_CLIENT_ID", "")
        self.GOOGLE_CLIENT_SECRET = env.get("GOOGLE_CLIENT_SECRET", "")
        self.GOOGLE_REDIRECT_URI = env.get("GOOGLE_REDIRECT_URI", "")
        # Cloud Tasks: exact-time start-now reminders.
        self.CLOUD_TASKS_LOCATION = env.get("CLOUD_TASKS_LOCATION", "us-central1")
        self.CLOUD_TASKS_QUEUE = env.get("CLOUD_TASKS_QUEUE", "")
        # Pub/Sub topic that receives every task event (no titles/notes).
        self.PUBSUB_EVENTS_TOPIC = env.get("PUBSUB_EVENTS_TOPIC", "")
        # BigQuery table that receives the same events for analytics.
        self.BQ_DATASET = env.get("BQ_DATASET", "")
        self.BQ_EVENTS_TABLE = env.get("BQ_EVENTS_TABLE", "task_events")
        # Cloud Storage bucket for uploaded PDFs and nightly DB backups.
        self.GCS_BUCKET = env.get("GCS_BUCKET", "")
        # Cloud Monitoring custom metrics.
        self.MONITORING_ENABLED = _flag(env.get("MONITORING_ENABLED", "0"))
        # "json" emits Cloud Logging's structured format on stdout.
        self.LOG_FORMAT = env.get("LOG_FORMAT", "text")

        self.FEATURE_ESTIMATES = _flag(env.get("FEATURE_ESTIMATES", "0"))
        self.FEATURE_SMART_CAPTURE = _flag(env.get("FEATURE_SMART_CAPTURE", "0"))
        self.FEATURE_INSIGHTS = _flag(env.get("FEATURE_INSIGHTS", "0"))
        # Voice assistant: spoken briefing, voice task capture, voice questions.
        self.FEATURE_VOICE = _flag(env.get("FEATURE_VOICE", "0"))
        self.ASSISTANT_NAME = env.get("ASSISTANT_NAME", "SARA").strip()[:30] or "SARA"

        self.SEED_USER_EMAIL = env.get("SEED_USER_EMAIL", "demo@startby.local")
        self.SEED_USER_PASSWORD = env.get("SEED_USER_PASSWORD", "change-me")

        self.WTF_CSRF_ENABLED = True
        self.ENV_NAME = env.get("FLASK_ENV", "development")
        # The login page's "DEMO demo@startby.local / change-me" autofill pill. Those
        # are the seed account's credentials (public in this repo), so it shows by
        # default only outside production; DEMO_LOGIN_HINT=1/0 overrides either way.
        self.DEMO_LOGIN_HINT = _flag(
            env.get("DEMO_LOGIN_HINT", "0" if self.ENV_NAME == "production" else "1")
        )
        self._raw_secret_key = env.get("SECRET_KEY", "")

        # The "Continue with Google/GitHub" buttons are a DEMO account picker:
        # /api/auth/social signs in as whatever email it is sent, with no
        # provider token check. That is a full account-takeover on any real
        # deployment, so it is off unless explicitly enabled (local demos only).
        self.ALLOW_DEMO_SOCIAL_LOGIN = _flag(env.get("ALLOW_DEMO_SOCIAL_LOGIN", "0"))
        # Set to 1 behind nginx so the client IP comes from X-Forwarded-For
        # (needed for per-IP rate limits) and cookies get the Secure flag.
        self.BEHIND_PROXY = _flag(env.get("BEHIND_PROXY", "0"))
        # 1 once the site is served over HTTPS: session cookies then carry
        # the Secure flag and responses send HSTS. Leave 0 for plain-HTTP dev
        # (a Secure cookie is never sent back over http://, so login breaks).
        self.SECURE_COOKIES = _flag(env.get("SECURE_COOKIES", "0"))

    _PLACEHOLDERS = ("change-me", "changeme", "replace-me")

    def validate_for_production(self) -> None:
        """Refuse to boot a production instance with a missing or placeholder
        secret. deploy/setup.sh copies .env.example (whose values are public
        in this repo) when nothing better is configured, and a service with
        Restart=always would otherwise come up with forgeable session cookies
        and a guessable cron secret."""
        if self.ENV_NAME != "production":
            return
        problems = []
        for name, value in (
            ("SECRET_KEY", self._raw_secret_key),
            ("CRON_SECRET", self.CRON_SECRET),
        ):
            if len(value) < 16 or any(p in value.lower() for p in self._PLACEHOLDERS):
                problems.append(name)
        if self.ALLOW_DEMO_SOCIAL_LOGIN:
            # /api/auth/social signs in as ANY email with no password: fine for a
            # local demo, account takeover for anyone on a real site.
            problems.append("ALLOW_DEMO_SOCIAL_LOGIN (must be off)")
        if problems:
            raise RuntimeError(
                "Refusing to start with FLASK_ENV=production: "
                + ", ".join(problems)
                + " is missing, too short, a placeholder, or a forbidden demo setting."
            )
