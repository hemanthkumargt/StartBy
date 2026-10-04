import tempfile
from pathlib import Path

import pytest

from app import create_app
from app.config import Config


@pytest.fixture(autouse=True)
def _signed_cookies_ignore_frozen_time(monkeypatch):
    """Session cookies are timestamped by itsdangerous. Several tests freeze
    the clock at a fixed past instant; a cookie minted outside the freeze
    (fixtures) then looks like it comes from the future once the real clock
    passes that instant, and is rejected. Timestamp cookies from the real
    clock, which freezegun exposes as real_time."""
    from freezegun import api
    from itsdangerous import timed

    monkeypatch.setattr(timed.TimestampSigner, "get_timestamp", lambda self: int(api.real_time()))


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


@pytest.fixture
def estimates_client(app):
    """A client with FEATURE_ESTIMATES on — reused across every Phase 2
    estimate/start-by/risk-radar test so each doesn't re-flip the flag."""
    app.config["FEATURE_ESTIMATES"] = True
    return app.test_client()


def register(client, name="Ada", email="ada@example.com", password="password123"):
    return client.post(
        "/api/auth/register",
        json={"name": name, "email": email, "password": password},
    )


def login(client, email="ada@example.com", password="password123"):
    return client.post("/api/auth/login", json={"email": email, "password": password})
