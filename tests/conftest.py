import tempfile
from pathlib import Path

import pytest

from app import create_app
from app.config import Config


@pytest.fixture
def app():
    with tempfile.TemporaryDirectory() as tmp_dir:
        config = Config(
            env={
                "SECRET_KEY": "test-secret",
                "DATABASE_PATH": str(Path(tmp_dir) / "test.db"),
                "DEFAULT_TIMEZONE": "Asia/Kolkata",
                "CRON_SECRET": "test-cron-secret",
            }
        )
        flask_app = create_app(config)
        # CSRFProtect needs a real browser round-trip to fetch the token;
        # the test client exercises route/service/repo logic, not that
        # transport concern, so it is switched off here only.
        flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        yield flask_app


@pytest.fixture
def client(app):
    return app.test_client()


def register(client, name="Ada", email="ada@example.com", password="password123"):
    return client.post(
        "/api/auth/register",
        json={"name": name, "email": email, "password": password},
    )


def login(client, email="ada@example.com", password="password123"):
    return client.post("/api/auth/login", json={"email": email, "password": password})
