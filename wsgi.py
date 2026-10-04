"""Entry point for Gunicorn: gunicorn --workers 2 wsgi:app"""

import os

from dotenv import load_dotenv

load_dotenv()

from app.gcp import secrets as gcp_secrets  # noqa: E402 — must follow load_dotenv

# Secret Manager values (SECRET_KEY, SMTP_PASSWORD, ...) must be in the
# environment before Config reads it, so this runs before create_app().
gcp_secrets.load_into_environ(os.environ)

from app import create_app  # noqa: E402 — must load .env + secrets first

app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
