import os


class Config:
    """Loaded from environment variables (set via .env in development)."""

    def __init__(self, env: dict[str, str] | None = None) -> None:
        env = env if env is not None else os.environ

        self.SECRET_KEY = env.get("SECRET_KEY", "dev-secret-key-change-me")
        self.DATABASE_PATH = env.get("DATABASE_PATH", "instance/app.db")
        self.DEFAULT_TIMEZONE = env.get("DEFAULT_TIMEZONE", "Asia/Kolkata")
        self.CRON_SECRET = env.get("CRON_SECRET", "")

        self.SMTP_HOST = env.get("SMTP_HOST", "smtp.gmail.com")
        self.SMTP_PORT = int(env.get("SMTP_PORT", "587"))
        self.SMTP_USER = env.get("SMTP_USER", "")
        self.SMTP_PASSWORD = env.get("SMTP_PASSWORD", "")

        self.GEMINI_API_KEY = env.get("GEMINI_API_KEY", "")
        self.GEMINI_MODEL = env.get("GEMINI_MODEL", "gemini-flash-latest")

        self.FEATURE_ESTIMATES = env.get("FEATURE_ESTIMATES", "0") == "1"
        self.FEATURE_SMART_CAPTURE = env.get("FEATURE_SMART_CAPTURE", "0") == "1"
        self.FEATURE_INSIGHTS = env.get("FEATURE_INSIGHTS", "0") == "1"

        self.WTF_CSRF_ENABLED = True
