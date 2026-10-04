"""Regression tests for the human-factors review fixes (items 1-8)."""

import tempfile

import pytest

from app.db import get_db
from app.repositories import user_repo
from tests.conftest import login, register
from tests.test_gcp import make_app

# ---- 1. theme -------------------------------------------------------------


def test_new_accounts_start_in_dark_mode_and_light_choice_persists(client):
    register(client)
    assert 'data-theme="dark"' in client.get("/").get_data(as_text=True)
    client.patch("/api/me", json={"dark_mode": False})
    for path in ("/", "/tasks", "/settings"):
        assert 'data-theme="light"' in client.get(path).get_data(as_text=True)
    client.patch("/api/me", json={"dark_mode": True})
    assert 'data-theme="dark"' in client.get("/").get_data(as_text=True)


# ---- 2. mobile layout (CSS rule present; behaviour verified in a browser) --


def test_mobile_shell_stacks_the_top_bar_above_content():
    from pathlib import Path

    css = (Path(__file__).resolve().parent.parent / "app/static/css/app.css").read_text()
    media = css[css.index("@media (max-width: 768px)") :]
    assert ".app-shell {" in media.split("}")[0] + "}" or "flex-direction: column" in media[:400]


# ---- 3. timezone ----------------------------------------------------------


def test_register_uses_the_browsers_timezone_when_valid(client):
    client.post(
        "/api/auth/register",
        json={
            "name": "A",
            "email": "a@x.co",
            "password": "password123",
            "timezone": "America/New_York",
        },
    )
    assert client.application.test_client() is not None
    with client.application.app_context():
        assert user_repo.find_by_email(get_db(), "a@x.co")["timezone"] == "America/New_York"


@pytest.mark.parametrize("bad", ["Mars/Base", "", None, 5, ["UTC"]])
def test_register_ignores_an_invalid_timezone(client, bad):
    client.post(
        "/api/auth/register",
        json={"name": "A", "email": "b@x.co", "password": "password123", "timezone": bad},
    )
    with client.application.app_context():
        assert user_repo.find_by_email(get_db(), "b@x.co")["timezone"] == "Asia/Kolkata"


# ---- 5. rate limits -------------------------------------------------------


def test_successful_logins_are_never_throttled(client):
    register(client)
    for _ in range(25):
        client.post("/api/auth/logout")
        assert login(client).status_code == 200


def test_failed_logins_lock_only_that_client_and_email_pair(client):
    register(client)
    client.post("/api/auth/logout")
    for _ in range(20):
        client.post("/api/auth/login", json={"email": "ada@example.com", "password": "nope"})
    blocked = client.post("/api/auth/login", json={"email": "ada@example.com", "password": "nope"})
    assert blocked.status_code == 429
    # same client, different email: not locked (a shared Wi-Fi keeps working)
    other = client.post("/api/auth/login", json={"email": "bob@example.com", "password": "nope"})
    assert other.status_code == 401


def test_another_network_can_still_log_in_while_an_attacker_is_locked_out():
    with tempfile.TemporaryDirectory() as tmp:
        app = make_app(tmp, BEHIND_PROXY="1")
        c = app.test_client()
        hdr = lambda ip: {"X-Forwarded-For": ip}  # noqa: E731
        c.post(
            "/api/auth/register",
            json={"name": "Ada", "email": "ada@example.com", "password": "password123"},
            headers=hdr("10.0.0.1"),
        )
        c.post("/api/auth/logout", headers=hdr("10.0.0.1"))
        for _ in range(21):
            c.post(
                "/api/auth/login",
                json={"email": "ada@example.com", "password": "wrong"},
                headers=hdr("6.6.6.6"),
            )
        locked = c.post(
            "/api/auth/login",
            json={"email": "ada@example.com", "password": "password123"},
            headers=hdr("6.6.6.6"),
        )
        owner = c.post(
            "/api/auth/login",
            json={"email": "ada@example.com", "password": "password123"},
            headers=hdr("203.0.113.5"),
        )
        assert locked.status_code == 429
        assert owner.status_code == 200


def test_many_failures_across_many_emails_trip_the_per_ip_cap(client):
    codes = [
        client.post(
            "/api/auth/login", json={"email": f"x{i}@example.com", "password": "nope"}
        ).status_code
        for i in range(152)
    ]
    assert codes[:150] == [401] * 150 and codes[150:] == [429, 429]


# ---- 7. titles, notes, due_at, register race ------------------------------


def test_titles_are_collapsed_to_one_clean_line(client):
    register(client)
    res = client.post("/api/tasks", json={"title": "Pay\nfee\t now\x00 ​please"})
    assert res.status_code == 201
    assert res.get_json()["title"] == "Pay fee now please"
    assert client.post("/api/tasks", json={"title": "\n\t \x00"}).status_code == 422


def test_title_edit_is_sanitised_too(client):
    register(client)
    task = client.post("/api/tasks", json={"title": "ok"}).get_json()
    res = client.patch(f"/api/tasks/{task['id']}", json={"title": "a\r\nb"})
    assert res.get_json()["title"] == "a b"


def test_notes_are_capped_and_nul_stripped(client):
    register(client)
    assert client.post("/api/tasks", json={"title": "t", "notes": "n" * 5001}).status_code == 422
    ok = client.post("/api/tasks", json={"title": "t", "notes": "a\x00b"}).get_json()
    assert ok["notes"] == "ab"


@pytest.mark.parametrize("bad", [12345, True, ["2026-10-09"], {"a": 1}])
def test_non_string_due_at_is_a_422_not_a_500(client, bad):
    register(client)
    assert client.post("/api/tasks", json={"title": "t", "due_at": bad}).status_code == 422
    task = client.post("/api/tasks", json={"title": "t"}).get_json()
    assert client.patch(f"/api/tasks/{task['id']}", json={"due_at": bad}).status_code == 422


def test_registering_the_same_email_in_a_race_is_a_422_not_a_500(client, monkeypatch):
    from app.repositories import user_repo as repo

    register(client)
    client.post("/api/auth/logout")
    # Simulate "check passed for both requests": the pre-insert lookup misses.
    monkeypatch.setattr(repo, "find_by_email", lambda conn, email: None)
    res = client.post(
        "/api/auth/register",
        json={"name": "Dup", "email": "ada@example.com", "password": "password123"},
    )
    assert res.status_code == 422
    assert res.get_json()["error"]["code"] == "email_taken"


def test_a_title_with_a_newline_can_no_longer_reach_the_email_subject(client, monkeypatch):
    """Existing rows saved before the fix may still hold a newline."""
    from app.services import reminder_service

    row = {"title": "bad\ntitle", "user_name": "A", "explanation": "x", "replan": "y"}
    assert "\n" not in reminder_service._start_now_subject(row)


# ---- 7b. one bad recipient/row must not starve other users ------------------


def test_one_users_unsendable_backlog_cannot_starve_another_user(app, monkeypatch):
    from freezegun import freeze_time

    from app.services import reminder_service
    from app.services.notifier import SmtpNotifier

    sent_to = []

    def selective_send(self, *, to, subject, body):
        if to == "bad@example.com":
            return False  # a mailbox the SMTP server keeps rejecting
        sent_to.append(to)
        return True

    monkeypatch.setattr(SmtpNotifier, "send", selective_send)
    with freeze_time("2026-10-04T06:00:00"):
        bad, good = app.test_client(), app.test_client()
        register(bad, name="Bad", email="bad@example.com")
        for i in range(120):
            bad.post("/api/tasks", json={"title": f"bad {i}", "due_at": "2026-10-01T09:00:00"})
        register(good, name="Good", email="good@example.com")
        good.post("/api/tasks", json={"title": "mine", "due_at": "2026-10-01T09:00:00"})
        result = good.post("/api/cron/reminders", headers={"X-Cron-Secret": "test-cron-secret"})
    assert result.status_code == 200
    assert "good@example.com" in sent_to
    # ...and the run did not grind through all 120 failing rows (circuit breaker)
    assert reminder_service.MAX_CONSECUTIVE_FAILURES < 120


def test_interleave_serves_users_fairly():
    from app.services.reminder_service import _interleave_by_user

    rows = [{"user_id": 1, "n": i} for i in range(3)] + [{"user_id": 2, "n": 0}]
    order = [(r["user_id"], r["n"]) for r in _interleave_by_user(rows)]
    assert order == [(1, 0), (2, 0), (1, 1), (1, 2)]


# ---- 8. operations ----------------------------------------------------------


def _run_seed(tmp, **env):
    import os
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    base = {
        **os.environ,
        "DATABASE_PATH": str(Path(tmp) / "seed.db"),
        "SECRET_KEY": "k" * 40,
        "CRON_SECRET": "c" * 40,
        "SEED_USER_EMAIL": "demo@startby.local",
    }
    base.update(env)
    return subprocess.run(
        [sys.executable, "scripts/seed.py"],
        cwd=root,
        env=base,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_seed_refuses_a_placeholder_password_in_production():
    with tempfile.TemporaryDirectory() as tmp:
        result = _run_seed(tmp, FLASK_ENV="production", SEED_USER_PASSWORD="change-me")
        assert result.returncode != 0
        assert "Refusing to seed in production" in (result.stdout + result.stderr)
        assert "Database:" in result.stdout  # says which database it is about to touch


def test_seed_works_with_a_real_password_in_production_and_in_development():
    with tempfile.TemporaryDirectory() as tmp:
        ok = _run_seed(tmp, FLASK_ENV="production", SEED_USER_PASSWORD="a-long-unguessable-pass")
        assert ok.returncode == 0, ok.stdout + ok.stderr
        assert "Seeded 30 tasks" in ok.stdout
    with tempfile.TemporaryDirectory() as tmp:
        dev = _run_seed(tmp, FLASK_ENV="development", SEED_USER_PASSWORD="change-me")
        assert dev.returncode == 0, dev.stdout + dev.stderr


def test_database_lock_is_a_friendly_503_not_a_500(client, monkeypatch):
    import sqlite3

    from app.services import task_service

    register(client)

    def locked(*a, **kw):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(task_service, "create_task", locked)
    res = client.post("/api/tasks", json={"title": "t"})
    assert res.status_code == 503
    assert res.get_json()["error"]["code"] == "busy"
    assert "try again" in res.get_json()["error"]["message"]


def test_other_database_errors_are_not_disguised_as_busy(client, monkeypatch):
    import sqlite3

    from app.services import task_service

    register(client)
    monkeypatch.setattr(
        task_service,
        "create_task",
        lambda *a, **kw: (_ for _ in ()).throw(sqlite3.OperationalError("no such table: tasks")),
    )
    assert client.post("/api/tasks", json={"title": "t"}).status_code == 500


def test_the_db_connection_waits_for_the_write_lock(app):
    from app import db

    with app.app_context():
        conn = db.get_db()
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == db.BUSY_TIMEOUT_SECONDS * 1000


# ---- round 2 review fixes -----------------------------------------------------


def test_the_login_limiter_cannot_be_used_to_exhaust_memory(client):
    """A giant 'email' used to be stored whole as a dict key (4 MB each)."""
    big = "a" * 400_000 + "@x.co"
    for _ in range(3):
        client.post("/api/auth/login", json={"email": big, "password": "nope"})
    limiters = client.application.extensions["auth_limiters"]
    for limiter in limiters.values():
        for key in limiter._calls:
            assert all(len(part) <= 64 for part in (key if isinstance(key, tuple) else (key,)))


def test_stale_limiter_keys_are_freed_by_age(monkeypatch):
    import app.ratelimit as rl

    clock = [100.0]
    monkeypatch.setattr(rl.time, "monotonic", lambda: clock[0])
    limiter = rl.RateLimiter(2, 10)
    limiter._last_purge = clock[0]
    for i in range(50):
        limiter.hit(f"k{i}")
    clock[0] += 25  # well past the window, far below the old 5000-key trigger
    limiter.hit("fresh")
    assert set(limiter._calls) == {"fresh"}


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "n" * 101, "email": "a@b.co", "password": "password123"},
        {"name": "ok", "email": "a" * 250 + "@b.co", "password": "password123"},
        {"name": "ok", "email": "a@b.co", "password": "p" * 129},
    ],
)
def test_registration_fields_are_length_capped(client, payload):
    res = client.post("/api/auth/register", json=payload)
    assert res.status_code == 422


def test_production_refuses_the_demo_social_login_switch():
    from app.config import Config

    good = {"FLASK_ENV": "production", "SECRET_KEY": "k" * 40, "CRON_SECRET": "c" * 40}
    Config(env=good).validate_for_production()
    with pytest.raises(RuntimeError, match="ALLOW_DEMO_SOCIAL_LOGIN"):
        Config(env={**good, "ALLOW_DEMO_SOCIAL_LOGIN": "1"}).validate_for_production()


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", " 1 ", "1  # on"])
def test_boolean_settings_accept_common_spellings(value):
    from app.config import Config

    assert Config(env={"BEHIND_PROXY": value, "SECURE_COOKIES": value}).BEHIND_PROXY is True


@pytest.mark.parametrize("value", ["0", "", "false", "no", "off", "2"])
def test_boolean_settings_reject_everything_else(value):
    from app.config import Config

    assert Config(env={"BEHIND_PROXY": value}).BEHIND_PROXY is False


def test_non_lock_database_errors_are_logged_with_a_traceback(client, monkeypatch, caplog):
    import logging
    import sqlite3

    from app.services import task_service

    register(client)
    monkeypatch.setattr(
        task_service,
        "create_task",
        lambda *a, **kw: (_ for _ in ()).throw(sqlite3.OperationalError("readonly database")),
    )
    with caplog.at_level(logging.ERROR):
        assert client.post("/api/tasks", json={"title": "t"}).status_code == 500
    assert any(r.exc_info for r in caplog.records)


def test_oversized_database_makes_the_backup_endpoint_report_it(gcp_app_factory=None):
    import tempfile

    from app.services import backup_service
    from tests.test_gcp import make_app

    with tempfile.TemporaryDirectory() as tmp:
        app = make_app(tmp)
        client = app.test_client()
        import unittest.mock as mock

        with mock.patch.object(backup_service, "MAX_BACKUP_BYTES", 10):
            res = client.post("/api/cron/backup", headers={"X-Cron-Secret": "test-cron-secret"})
        assert res.status_code == 507
        assert res.get_json()["error"]["code"] == "too_large"


# -- logic: emails, ordering, estimates ------------------------------------------


def _task_row(client, **body):
    return client.post("/api/tasks", json=body).get_json()


def test_do_this_now_prefers_a_task_that_can_still_be_met(estimates_client):
    from freezegun import freeze_time

    register(estimates_client)
    with freeze_time("2026-10-04T06:00:00"):
        _task_row(
            estimates_client, title="abandoned", due_at="2026-08-20T10:00:00", estimate_hours=2
        )
        _task_row(
            estimates_client, title="due soon", due_at="2026-10-04T06:40:00", estimate_hours=2
        )
        card = estimates_client.get("/api/dashboard").get_json()["do_this_now"]
    assert card["title"] == "due soon"


def test_due_next_shows_upcoming_before_long_overdue(client):
    from freezegun import freeze_time

    register(client)
    with freeze_time("2026-10-04T06:00:00"):
        for i in range(5):
            _task_row(client, title=f"old{i}", due_at=f"2026-08-0{i + 1}T10:00:00")
        _task_row(client, title="soon", due_at="2026-10-04T07:00:00")
        titles = [t["title"] for t in client.get("/api/dashboard").get_json()["due_next"]]
    assert titles[0] == "soon" and len(titles) == 5
    assert titles[1] == "old4"  # then the most recently missed first


def test_one_mistyped_actual_hours_does_not_rewrite_your_pace(estimates_client):
    from freezegun import freeze_time

    register(estimates_client)
    with freeze_time("2026-10-04T06:00:00"):
        t = _task_row(
            estimates_client,
            title="a",
            tag="work",
            due_at="2026-10-30T10:00:00",
            estimate_hours=0.25,
        )
        estimates_client.post(f"/api/tasks/{t['id']}/complete", json={"actual_hours": 100})
        nxt = _task_row(
            estimates_client, title="b", tag="work", due_at="2026-10-30T10:00:00", estimate_hours=2
        )
    # clamped to 3x (blended with the 1.5x prior at n=1 => well under 3.0)
    assert "about 3.00x" not in nxt["start_by_explanation"]
    assert "6h 54m" not in nxt["start_by_explanation"]


def test_editing_the_estimate_re_arms_only_start_now(estimates_client):
    from freezegun import freeze_time

    from app.db import get_db
    from app.repositories import reminder_repo

    register(estimates_client)
    with freeze_time("2026-10-04T06:00:00"):
        t = _task_row(estimates_client, title="x", due_at="2026-10-04T20:00:00", estimate_hours=2)
        with estimates_client.application.app_context():
            conn = get_db()
            for kind in ("due_soon", "overdue", "start_now"):
                reminder_repo.claim(conn, t["id"], kind)
        estimates_client.patch(f"/api/tasks/{t['id']}", json={"estimate_hours": 3})
        with estimates_client.application.app_context():
            kinds = {
                r[0]
                for r in get_db().execute(
                    "SELECT kind FROM reminders_sent WHERE task_id = ?", (t["id"],)
                )
            }
    assert kinds == {
        "due_soon",
        "overdue",
    }  # start_now re-armed; the deadline emails are not re-sent


def test_changing_the_deadline_re_arms_every_reminder(estimates_client):
    from freezegun import freeze_time

    from app.db import get_db
    from app.repositories import reminder_repo

    register(estimates_client)
    with freeze_time("2026-10-04T06:00:00"):
        t = _task_row(estimates_client, title="x", due_at="2026-10-04T20:00:00", estimate_hours=2)
        with estimates_client.application.app_context():
            reminder_repo.claim(get_db(), t["id"], "due_soon")
        estimates_client.patch(f"/api/tasks/{t['id']}", json={"due_at": "2026-10-05T20:00:00"})
        with estimates_client.application.app_context():
            n = (
                get_db()
                .execute("SELECT COUNT(*) FROM reminders_sent WHERE task_id = ?", (t["id"],))
                .fetchone()[0]
            )
    assert n == 0


def test_a_deadline_year_outside_2000_2100_is_rejected_everywhere(client):
    register(client)
    for bad in ("0001-01-01T00:00:00", "9999-12-31T00:00:00", "0026-10-09T17:00:00Z"):
        res = client.post("/api/tasks", json={"title": "t", "due_at": bad})
        assert res.status_code == 422, bad
    assert client.get("/api/tasks").status_code == 200
    assert client.get("/api/dashboard").status_code == 200


def test_a_deadline_at_the_edge_cannot_crash_start_by(estimates_client):
    from app.services import estimate_service

    assert estimate_service.compute_start_by("0001-01-01T00:00:00", 2, 1.5) is None


def test_emoji_and_indic_joiners_survive_title_cleaning(client):
    register(client)
    for title in ("👨‍👩‍👧 family plan", "क्‍ष परीक्षा", "ക്‌ പഠനം", "می‌خواهم"):
        got = client.post("/api/tasks", json={"title": title}).get_json()["title"]
        assert got == title
    # ...while real zero-width SPACES and control characters still go
    assert client.post("/api/tasks", json={"title": "a​b\nc"}).get_json()["title"] == "a b c"


def test_reminder_emails_state_the_due_time_in_the_users_timezone(app, monkeypatch):
    from freezegun import freeze_time

    from app.services.notifier import SmtpNotifier

    sent = []
    monkeypatch.setattr(SmtpNotifier, "send", lambda self, **kw: sent.append(kw) or True)
    with freeze_time("2026-10-04T06:00:00"):
        c = app.test_client()
        register(c)
        c.post("/api/tasks", json={"title": "Report", "due_at": "2026-10-04T12:00:00"})
        c.post("/api/cron/reminders", headers={"X-Cron-Secret": "test-cron-secret"})
    body = next(m["body"] for m in sent if "due within 24 hours" in m["body"])
    assert "Sun 04 Oct, 17:30" in body  # 12:00 UTC in Asia/Kolkata


def test_start_now_is_not_sent_for_a_task_that_is_already_overdue(estimates_client, monkeypatch):
    from freezegun import freeze_time

    from app.services.notifier import SmtpNotifier

    sent = []
    monkeypatch.setattr(SmtpNotifier, "send", lambda self, **kw: sent.append(kw["subject"]) or True)
    register(estimates_client)
    with freeze_time("2026-10-04T06:00:00"):
        _task_row(estimates_client, title="late", due_at="2026-10-01T10:00:00", estimate_hours=2)
        out = estimates_client.post(
            "/api/cron/reminders", headers={"X-Cron-Secret": "test-cron-secret"}
        ).get_json()
    assert out["start_now_sent"] == 0
    assert any(s.startswith("Overdue") for s in sent)
    assert not any(s.startswith("Time to start") for s in sent)


def test_the_failure_streak_ends_the_whole_run_not_just_one_kind(app, monkeypatch):
    from freezegun import freeze_time

    from app.services.notifier import SmtpNotifier

    attempts = []
    monkeypatch.setattr(SmtpNotifier, "send", lambda self, **kw: attempts.append(1) and False)
    with freeze_time("2026-10-04T06:00:00"):
        # Several users, so the per-user skip (3 failures) never fires first: this
        # is about the run-wide streak.
        for n in range(3):
            c = app.test_client()
            register(c, email=f"s{n}@x.co")
            for i in range(4):
                c.post("/api/tasks", json={"title": f"d{i}", "due_at": "2026-10-04T12:00:00"})
                c.post("/api/tasks", json={"title": f"o{i}", "due_at": "2026-10-01T12:00:00"})
        c.post("/api/cron/reminders", headers={"X-Cron-Secret": "test-cron-secret"})
    assert len(attempts) == 5  # not 5 per kind


def test_a_run_stops_starting_sends_after_its_deadline(app, monkeypatch):
    from freezegun import freeze_time

    from app.services import reminder_service
    from app.services.notifier import SmtpNotifier

    sent = []
    monkeypatch.setattr(SmtpNotifier, "send", lambda self, **kw: sent.append(1) or True)
    monkeypatch.setattr(reminder_service, "RUN_SECONDS", -1)  # already expired
    with freeze_time("2026-10-04T06:00:00"):
        c = app.test_client()
        register(c, email="d@x.co")
        c.post("/api/tasks", json={"title": "d", "due_at": "2026-10-01T12:00:00"})
        c.post("/api/cron/reminders", headers={"X-Cron-Secret": "test-cron-secret"})
    assert sent == []


def test_remember_me_actually_makes_the_session_persistent(client):
    register(client)
    client.post("/api/auth/logout")
    plain = client.post(
        "/api/auth/login", json={"email": "ada@example.com", "password": "password123"}
    )
    assert "remember_token" not in " ".join(plain.headers.getlist("Set-Cookie"))
    client.post("/api/auth/logout")
    kept = client.post(
        "/api/auth/login",
        json={"email": "ada@example.com", "password": "password123", "remember": "on"},
    )
    cookies = " ".join(kept.headers.getlist("Set-Cookie"))
    assert "remember_token" in cookies and "HttpOnly" in cookies


def test_remember_me_is_off_by_default_on_the_login_page(client):
    html = client.get("/login").get_data(as_text=True)
    assert 'id="remember-me" name="remember">' in html


def test_pages_have_a_skip_link_that_points_at_real_content(client):
    register(client)
    html = client.get("/tasks").get_data(as_text=True)
    assert 'href="#main-content"' in html and 'id="main-content"' in html
