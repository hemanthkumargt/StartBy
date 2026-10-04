import tempfile

from app.ratelimit import RateLimiter
from tests.conftest import register
from tests.test_gcp import make_app


def test_login_is_rate_limited_per_client(client):
    register(client)
    client.post("/api/auth/logout")
    statuses = [
        client.post(
            "/api/auth/login", json={"email": "ada@example.com", "password": "wrong"}
        ).status_code
        for _ in range(22)
    ]
    assert statuses[:20] == [401] * 20
    assert statuses[20:] == [429, 429]
    # Even the right password is refused while throttled: that is the point.
    good = client.post(
        "/api/auth/login", json={"email": "ada@example.com", "password": "password123"}
    )
    assert good.status_code == 429
    assert good.get_json()["error"]["code"] == "rate_limited"


def test_registration_allows_a_room_full_of_signups_then_throttles(client):
    codes = [
        client.post(
            "/api/auth/register",
            json={"name": "U", "email": f"u{i}@example.com", "password": "password123"},
        ).status_code
        for i in range(32)
    ]
    assert codes[:30] == [201] * 30
    assert codes[30:] == [429, 429]


def test_limits_do_not_leak_between_app_instances(app):
    a = app.test_client()
    for _ in range(21):
        a.post("/api/auth/login", json={"email": "x@example.com", "password": "p"})
    with tempfile.TemporaryDirectory() as tmp:
        fresh = make_app(tmp).test_client()
        res = fresh.post("/api/auth/login", json={"email": "x@example.com", "password": "p"})
        assert res.status_code == 401  # not 429


def test_security_headers_on_pages_and_api(client):
    for path in ("/login", "/api/tasks"):
        headers = client.get(path).headers
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["X-Frame-Options"] == "DENY"
        assert headers["Referrer-Policy"] == "same-origin"
        assert "Strict-Transport-Security" not in headers  # plain-HTTP default


def test_secure_cookie_mode_adds_hsts_and_secure_flag():
    with tempfile.TemporaryDirectory() as tmp:
        app = make_app(tmp, SECURE_COOKIES="1")
        client = app.test_client()
        response = client.post(
            "/api/auth/register",
            json={"name": "A", "email": "a@example.com", "password": "password123"},
        )
        cookie = response.headers["Set-Cookie"]
        assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=Lax" in cookie
        assert "max-age=31536000" in response.headers["Strict-Transport-Security"]


def test_session_cookie_is_httponly_and_samesite_lax_by_default(client):
    cookie = register(client).headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie
    assert "Secure" not in cookie


def test_client_ip_comes_from_forwarded_header_only_behind_the_proxy():
    with tempfile.TemporaryDirectory() as tmp:
        app = make_app(tmp, BEHIND_PROXY="1")
        client = app.test_client()
        seen = []

        @app.get("/__ip")
        def ip():
            from flask import request

            seen.append(request.remote_addr)
            return "ok"

        client.get("/__ip", headers={"X-Forwarded-For": "203.0.113.9"})
        assert seen == ["203.0.113.9"]
    with tempfile.TemporaryDirectory() as tmp:
        app = make_app(tmp)  # not behind a proxy: header must be ignored (spoofable)
        client = app.test_client()
        seen2 = []

        @app.get("/__ip")
        def ip2():
            from flask import request

            seen2.append(request.remote_addr)
            return "ok"

        client.get("/__ip", headers={"X-Forwarded-For": "203.0.113.9"})
        assert seen2 == ["127.0.0.1"]


def test_rate_limiter_window_and_key_purge(monkeypatch):
    import app.ratelimit as rl

    clock = [100.0]
    monkeypatch.setattr(rl.time, "monotonic", lambda: clock[0])
    limiter = RateLimiter(2, 10)
    assert limiter.allow("a") and limiter.allow("a") and not limiter.allow("a")
    assert limiter.allow("b")  # independent keys
    clock[0] += 11
    assert limiter.allow("a")  # window slid
    monkeypatch.setattr(rl, "_PURGE_AT_KEYS", 3)
    for i in range(5):
        limiter.allow(f"k{i}")
    clock[0] += 11
    limiter.allow("trigger")
    assert len(limiter._calls) < 5  # stale keys were dropped


def test_logout_clears_a_pending_calendar_oauth_state(client):
    register(client)
    with client.session_transaction() as sess:
        sess["calendar_oauth_state"] = "pending"
    client.post("/api/auth/logout")
    with client.session_transaction() as sess:
        assert "calendar_oauth_state" not in sess
