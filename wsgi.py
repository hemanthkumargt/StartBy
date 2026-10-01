"""Entry point for Gunicorn: gunicorn --workers 2 wsgi:app"""

from dotenv import load_dotenv

load_dotenv()

from app import create_app  # noqa: E402 — must load .env first

app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
