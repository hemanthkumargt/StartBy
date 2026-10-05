import tempfile
import urllib.parse

import pytest
from freezegun import freeze_time

from app.db import get_db
from app.gcp import dispatcher, rest
from app.repositories import calendar_repo
from app.services import calendar_service
from tests.conftest import register
from tests.test_gcp import make_app

NOW = "2026-10-04T06:00:00"
TOKEN_URL = "https://oauth2.googleapis.com/token"


class FakeGoogle:
    """Routes the REST calls Calendar makes; records them."""

    def __init__(self):
        self.calls = []
        self.events = {}
        self.cancelled = set()  # deleted ids Google still reserves
        self.fail = {}  # (method, fragment) -> HTTP status to raise
        self.token_error = None

    def __call__(self, method, url, **kw):
        self.calls.append({"method": method, "url": url, **kw})
        for (m, fragment), status in self.fail.items():
            if m == method and fragment in url:
                if isinstance(status, tuple):
                    raise rest.GcpError(f"HTTP {status[0]}", *status)
                raise rest.GcpError(f"HTTP {status}", status)
        if url == TOKEN_URL:
            form = dict(urllib.parse.parse_qsl(kw["raw_body"].decode()))
            if form["grant_type"] == "authorization_code":
                return {"refresh_token": f"rt-{form['code']}", "access_token": "x"}
            if self.token_error:
                status, code = self.token_error
                raise rest.GcpError(f"HTTP {status}", status, code)
            return {"access_token": f"at-for-{form['refresh_token']}", "expires_in": 3600}
        if url.endswith("/events") and method == "POST":
            event_id = kw["body"]["id"]
            if event_id in self.events or event_id in self.cancelled:
                raise rest.GcpError("HTTP 409", 409)
            self.events[event_id] = kw["body"]
            return {"id": event_id}
        event_id = url.rsplit("/", 1)[1]
        if method == "PATCH":
            if event_id not in self.events and event_id not in self.cancelled:
                raise rest.GcpError("HTTP 404", 404)
            self.cancelled.discard(event_id)  # status=confirmed revives it
            self.events[event_id] = kw["body"]
        if method == "DELETE":
            if event_id not in self.events:
                raise rest.GcpError("HTTP 404", 404)
            del self.events[event_id]
            self.cancelled.add(event_id)
        return {}

    def to(self, method, fragment):
        return [c for c in self.calls if c["method"] == method and fragment in c["url"]]


@pytest.fixture(autouse=True)
def _sync():
    dispatcher.synchronous = True
    calendar_service._token_cache.clear()
    yield
    dispatcher.synchronous = False


@pytest.fixture
def google(monkeypatch):
    fake = FakeGoogle()
    monkeypatch.setattr(rest, "request_json", fake)
    return fake


@pytest.fixture
def cal_app():
    with tempfile.TemporaryDirectory() as tmp:
        yield make_app(
            tmp,
            GOOGLE_CLIENT_ID="cid.apps.googleusercontent.com",
            GOOGLE_CLIENT_SECRET="csecret",
            GOOGLE_REDIRECT_URI="http://localhost:5050/calendar/callback",
            # Isolate Calendar from the other integrations' calls.
            PUBSUB_EVENTS_TOPIC="",
            BQ_DATASET="",
            CLOUD_TASKS_QUEUE="",
            GCS_BUCKET="",
            MONITORING_ENABLED="0",
        )


def connect(app, client, code="code1", user_email="ada@example.com"):
    """Run the real connect -> callback round trip for a logged-in client."""
    redirect = client.get("/calendar/connect")
    assert redirect.status_code == 302
    state = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(redirect.location).query))["state"]
    return client.get(f"/calendar/callback?code={code}&state={state}")


def new_task(client, **over):
    body = {
        "title": "Write report",
        "tag": "work",
        "due_at": "2026-10-09T12:00:00",
        "estimate_hours": 2,
    }
    body.update(over)
    return client.post("/api/tasks", json=body).get_json()


@pytest.fixture
def linked(cal_app, google):
    client = cal_app.test_client()
    register(client)
    assert connect(cal_app, client).status_code == 302
    google.calls.clear()
    return cal_app, client, google


# ---- availability + OAuth flow ------------------------------------------


def test_calendar_unavailable_when_not_configured(app):
    client = app.test_client()
    register(client)
    assert client.get("/api/calendar/status").get_json() == {
        "available": False,
        "connected": False,
    }
    assert client.get("/calendar/connect").status_code == 404
    assert client.get("/calendar/callback?code=x&state=y").status_code == 404
    assert b"calendar-card" not in client.get("/settings").data


def test_settings_shows_calendar_card_when_configured(cal_app):
    client = cal_app.test_client()
    register(client)
    assert b"calendar-card" in client.get("/settings").data


def test_connect_redirects_to_google_with_narrow_scope_and_state(cal_app):
    client = cal_app.test_client()
    register(client)
    response = client.get("/calendar/connect")
    assert response.status_code == 302
    parts = urllib.parse.urlsplit(response.location)
    query = dict(urllib.parse.parse_qsl(parts.query))
    assert parts.netloc == "accounts.google.com"
    assert query["scope"] == "https://www.googleapis.com/auth/calendar.events"
    assert query["client_id"] == "cid.apps.googleusercontent.com"
    assert query["access_type"] == "offline" and query["prompt"] == "consent"
    assert len(query["state"]) >= 32
    assert "csecret" not in response.location


def test_connect_requires_login(cal_app):
    response = cal_app.test_client().get("/calendar/connect")
    assert response.status_code in (302, 401)
    assert "accounts.google.com" not in (response.location or "")


def test_callback_rejects_missing_or_wrong_state_and_replays(cal_app, google):
    client = cal_app.test_client()
    register(client)
    assert client.get("/calendar/callback?code=c&state=forged").status_code == 400
    client.get("/calendar/connect")
    assert client.get("/calendar/callback?code=c&state=forged").status_code == 400
    # a correct state works once, then is spent
    redirect = client.get("/calendar/connect")
    state = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(redirect.location).query))["state"]
    assert client.get(f"/calendar/callback?code=c&state={state}").status_code == 302
    assert client.get(f"/calendar/callback?code=c&state={state}").status_code == 400
    assert not google.to("POST", "forged")


def test_callback_with_non_ascii_state_is_a_clean_400_not_a_500(cal_app, google):
    client = cal_app.test_client()
    register(client)
    client.get("/calendar/connect")
    assert client.get("/calendar/callback?code=c&state=%C3%A9%E2%82%AC").status_code == 400


def test_callback_user_denial_redirects_without_linking(cal_app, google):
    client = cal_app.test_client()
    register(client)
    redirect = client.get("/calendar/connect")
    state = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(redirect.location).query))["state"]
    response = client.get(f"/calendar/callback?error=access_denied&state={state}")
    assert response.status_code == 302 and response.location.endswith("calendar=denied")
    assert client.get("/api/calendar/status").get_json()["connected"] is False


def test_callback_stores_refresh_token_and_status_reports_connected(cal_app, google):
    client = cal_app.test_client()
    register(client)
    response = connect(cal_app, client, code="abc")
    assert response.location.endswith("calendar=connected")
    assert client.get("/api/calendar/status").get_json()["connected"] is True
    exchange = google.to("POST", "oauth2.googleapis.com/token")[0]
    form = dict(urllib.parse.parse_qsl(exchange["raw_body"].decode()))
    assert form["grant_type"] == "authorization_code" and form["code"] == "abc"
    with cal_app.app_context():
        assert calendar_repo.get_link(get_db(), 1)["refresh_token"] == "rt-abc"


def test_token_exchange_failure_redirects_to_settings_and_makes_no_link(cal_app, google):
    google.fail[("POST", "oauth2.googleapis.com/token")] = 400
    client = cal_app.test_client()
    register(client)
    response = connect(cal_app, client)
    assert response.status_code == 302 and response.location.endswith("calendar=error")
    assert client.get("/api/calendar/status").get_json()["connected"] is False


@freeze_time(NOW)
def test_connecting_backfills_existing_pending_tasks(cal_app, google):
    client = cal_app.test_client()
    register(client)
    new_task(client, title="Existing A")
    new_task(client, title="Existing B")
    done = new_task(client, title="Already done")
    client.post(f"/api/tasks/{done['id']}/complete")
    connect(cal_app, client)
    summaries = sorted(e["summary"] for e in google.events.values())
    assert summaries == ["Work on: Existing A", "Work on: Existing B"]


# ---- sync lifecycle -----------------------------------------------------


@freeze_time(NOW)
def test_new_task_becomes_a_block_from_start_by_to_due(linked):
    _, client, google = linked
    new_task(client)  # 2h * 1.5 * 1.15 = 3h27m before 12:00 -> 08:33
    (post,) = google.to("POST", "/events")
    assert post["bearer"] == "at-for-rt-code1"
    assert post["body"]["summary"] == "Work on: Write report"
    assert post["body"]["start"] == {"dateTime": "2026-10-09T08:33:00Z"}
    assert post["body"]["end"] == {"dateTime": "2026-10-09T12:00:00Z"}
    assert "You estimated 2h" in post["body"]["description"]


@freeze_time(NOW)
def test_deadline_only_task_gets_a_30_minute_block_ending_at_due(linked):
    _, client, google = linked
    client.post("/api/tasks", json={"title": "Pay fee", "due_at": "2026-10-09T12:00:00"})
    (post,) = google.to("POST", "/events")
    assert post["body"]["start"] == {"dateTime": "2026-10-09T11:30:00Z"}
    assert post["body"]["end"] == {"dateTime": "2026-10-09T12:00:00Z"}


@freeze_time(NOW)
def test_task_without_deadline_is_not_synced(linked):
    _, client, google = linked
    client.post("/api/tasks", json={"title": "Someday"})
    assert google.calls == []


def eid(task):
    return calendar_service.event_id_for(1, task["id"])


@freeze_time(NOW)
def test_event_ids_are_deterministic_per_user_and_task():
    a = calendar_service.event_id_for(1, 5)
    assert a == calendar_service.event_id_for(1, 5)
    assert a != calendar_service.event_id_for(2, 5) != calendar_service.event_id_for(1, 6)
    assert 5 <= len(a) <= 1024 and set(a) <= set("0123456789abcdefghijklmnopqrstuv")


@freeze_time(NOW)
def test_creating_posts_with_the_deterministic_id(linked):
    _, client, google = linked
    task = new_task(client)
    (post,) = google.to("POST", "/events")
    assert post["body"]["id"] == eid(task)
    assert list(google.events) == [eid(task)]


@freeze_time(NOW)
def test_editing_patches_the_same_event_instead_of_duplicating(linked):
    _, client, google = linked
    task = new_task(client)
    client.patch(f"/api/tasks/{task['id']}", json={"due_at": "2026-10-10T12:00:00"})
    assert len(google.to("POST", "/events")) == 1
    (patch,) = google.to("PATCH", f"/events/{eid(task)}")
    assert patch["body"]["end"] == {"dateTime": "2026-10-10T12:00:00Z"}
    assert patch["body"]["status"] == "confirmed"
    assert len(google.events) == 1


@freeze_time(NOW)
def test_event_deleted_by_user_is_recreated_on_next_edit(linked):
    _, client, google = linked
    task = new_task(client)
    google.events.pop(eid(task))  # user deleted it in Google Calendar (404 on PATCH)
    client.patch(f"/api/tasks/{task['id']}", json={"title": "Renamed"})
    assert len(google.to("POST", "/events")) == 2
    assert [e["summary"] for e in google.events.values()] == ["Work on: Renamed"]


@freeze_time(NOW)
def test_a_racing_second_worker_updates_instead_of_duplicating(linked):
    """Two workers both see 'no mapping yet' and both POST the same id: Google
    answers the loser 409, which becomes an update — one event, not two."""
    app, client, google = linked
    task = new_task(client)
    with app.app_context():
        calendar_repo.delete_event(get_db(), task["id"])  # the loser has no mapping row
    client.patch(f"/api/tasks/{task['id']}", json={"title": "Edited"})
    assert len(google.events) == 1
    assert [e["summary"] for e in google.events.values()] == ["Work on: Edited"]


@freeze_time(NOW)
def test_completing_removes_the_event_and_reopening_restores_the_same_one(linked):
    app, client, google = linked
    task = new_task(client)
    client.post(f"/api/tasks/{task['id']}/complete")
    assert google.to("DELETE", f"/events/{eid(task)}") and google.events == {}
    with app.app_context():
        assert calendar_repo.get_event(get_db(), task["id"]) is None
    client.post(f"/api/tasks/{task['id']}/reopen")
    # The id is still reserved by the deleted event: POST -> 409 -> PATCH revives it.
    assert list(google.events) == [eid(task)]
    assert eid(task) not in google.cancelled


@freeze_time(NOW)
def test_deleting_removes_event_and_tolerates_already_gone(linked):
    _, client, google = linked
    gone = new_task(client, title="a")
    google.events.clear()  # already gone in Google: DELETE answers 404
    assert client.delete(f"/api/tasks/{gone['id']}").status_code == 204


@freeze_time(NOW)
def test_no_calendar_calls_for_users_who_never_connected(cal_app, google):
    client = cal_app.test_client()
    register(client)
    new_task(client)
    assert google.calls == []


@freeze_time(NOW)
def test_each_user_syncs_with_their_own_token_only(cal_app, google):
    a, b = cal_app.test_client(), cal_app.test_client()
    register(a)
    register(b, name="Bo", email="bo@example.com")
    connect(cal_app, a, code="A")
    connect(cal_app, b, code="B")
    google.calls.clear()
    new_task(a, title="A's task")
    new_task(b, title="B's task")
    posts = google.to("POST", "/events")
    assert [(p["bearer"], p["body"]["summary"]) for p in posts] == [
        ("at-for-rt-A", "Work on: A's task"),
        ("at-for-rt-B", "Work on: B's task"),
    ]


@freeze_time(NOW)
def test_access_token_is_cached_between_syncs(linked):
    _, client, google = linked
    new_task(client, title="one")
    new_task(client, title="two")
    assert len(google.to("POST", "oauth2.googleapis.com/token")) == 1


@freeze_time(NOW)
def test_revoked_token_disconnects_cleanly_and_never_breaks_the_task_write(linked):
    app, client, google = linked
    google.token_error = (400, "invalid_grant")
    response = client.post(
        "/api/tasks", json={"title": "t", "due_at": "2026-10-09T12:00:00", "estimate_hours": 1}
    )
    assert response.status_code == 201
    assert client.get("/api/calendar/status").get_json()["connected"] is False


@pytest.mark.parametrize(
    "status,code",
    [(400, "invalid_client"), (400, "invalid_request"), (401, "invalid_client"), (400, "")],
)
@freeze_time(NOW)
def test_non_invalid_grant_token_errors_keep_the_link_and_log_an_error(
    linked, caplog, status, code
):
    app, client, google = linked
    google.token_error = (status, code)
    with caplog.at_level("ERROR"):
        response = client.post(
            "/api/tasks", json={"title": "t", "due_at": "2026-10-09T12:00:00", "estimate_hours": 1}
        )
    assert response.status_code == 201
    assert client.get("/api/calendar/status").get_json()["connected"] is True
    assert "calendar_token_refused" in caplog.text
    # ...and once Google accepts the client again, the next edit syncs.
    google.token_error = None
    new_task(client, title="again")
    assert [e["summary"] for e in google.events.values()] == ["Work on: again"]


@freeze_time(NOW)
def test_calendar_rate_limit_403_is_retried_once_with_backoff(linked, monkeypatch):
    _, client, google = linked
    sleeps = []
    monkeypatch.setattr(calendar_service.time, "sleep", sleeps.append)
    real_call = google.__call__
    state = {"n": 0}

    def flaky(method, url, **kw):
        if method == "POST" and url.endswith("/events"):
            state["n"] += 1
            if state["n"] == 1:
                google.calls.append({"method": method, "url": url, **kw})
                raise rest.GcpError("HTTP 403", 403, "userRateLimitExceeded")
        return real_call(method, url, **kw)

    monkeypatch.setattr(rest, "request_json", flaky)
    new_task(client)
    assert state["n"] == 2 and len(google.events) == 1
    assert sleeps == [calendar_service.RATE_LIMIT_BACKOFF_SECONDS]


@freeze_time(NOW)
def test_other_403_is_not_retried(linked, monkeypatch):
    _, client, google = linked
    sleeps = []
    monkeypatch.setattr(calendar_service.time, "sleep", sleeps.append)
    google.fail[("POST", "/events")] = (403, "forbidden")
    new_task(client)
    assert sleeps == [] and len(google.to("POST", "/events")) == 1


@freeze_time(NOW)
def test_google_outage_never_fails_the_task_write(linked):
    _, client, google = linked
    google.fail[("POST", "/events")] = 503
    assert new_task(client)["title"] == "Write report"


# ---- disconnect ---------------------------------------------------------


def test_disconnect_revokes_grant_and_forgets_link(linked):
    app, client, google = linked
    assert client.post("/api/calendar/disconnect").status_code == 204
    revoke = google.to("POST", "oauth2.googleapis.com/revoke")
    assert dict(urllib.parse.parse_qsl(revoke[0]["raw_body"].decode())) == {"token": "rt-code1"}
    assert client.get("/api/calendar/status").get_json()["connected"] is False
    assert client.post("/api/calendar/disconnect").status_code == 204  # idempotent
    assert len(google.to("POST", "oauth2.googleapis.com/revoke")) == 1


@freeze_time(NOW)
def test_disconnect_removes_the_events_it_created_before_revoking(linked):
    _, client, google = linked
    a, b = new_task(client, title="A"), new_task(client, title="B")
    assert len(google.events) == 2
    client.post("/api/calendar/disconnect")
    assert google.events == {}
    methods = [c["method"] + c["url"].rsplit("/", 1)[-1] for c in google.calls]
    assert methods[-1] == "POSTrevoke"  # revoked only after the events were deleted
    assert {eid(a), eid(b)} <= google.cancelled


@freeze_time(NOW)
def test_reconnecting_reuses_the_same_event_ids_no_lookalikes(linked):
    app, client, google = linked
    task = new_task(client)
    client.post("/api/calendar/disconnect")
    connect(app, client, code="code2")
    assert list(google.events) == [eid(task)]  # revived, not duplicated


@freeze_time(NOW)
def test_token_cache_is_keyed_by_refresh_token_so_a_new_google_account_is_used(cal_app, google):
    client = cal_app.test_client()
    register(client)
    connect(cal_app, client, code="first")
    new_task(client, title="one")
    # Simulate the OTHER worker: the link changes without this process's cache cleared.
    with cal_app.app_context():
        calendar_repo.upsert_link(get_db(), 1, "rt-second-account")
    google.calls.clear()
    new_task(client, title="two")
    post = google.to("POST", "/events")[-1]
    assert post["bearer"] == "at-for-rt-second-account"


@freeze_time(NOW)
def test_background_connection_enforces_foreign_keys(linked):
    app, client, google = linked
    from app.services.calendar_service import CalendarSync

    sync = CalendarSync(app.config)
    sync._sync(
        {"id": 999, "status": "pending", "due_at": "2026-10-09T12:00:00", "title": "ghost"}, 1
    )
    with app.app_context():
        assert calendar_repo.get_event(get_db(), 999) is None  # FK rejected the orphan row


def test_backups_never_contain_calendar_refresh_tokens(linked):
    import gzip
    import sqlite3
    import tempfile
    from pathlib import Path

    from app.services import backup_service

    app, _, _ = linked
    blob = gzip.decompress(backup_service.snapshot_gzip(app.config["DATABASE_PATH"]))
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "b.db"
        path.write_bytes(blob)
        restored_db = sqlite3.connect(path)
        try:
            tokens = [r[0] for r in restored_db.execute("SELECT refresh_token FROM calendar_links")]
        finally:
            restored_db.close()
    assert tokens == [""]
    with app.app_context():  # the live database keeps the real token
        assert calendar_repo.get_link(get_db(), 1)["refresh_token"] == "rt-code1"


def test_disconnect_requires_login(cal_app):
    assert cal_app.test_client().post("/api/calendar/disconnect").status_code == 401


# ---- event_body ---------------------------------------------------------


def test_event_body_falls_back_when_start_by_is_not_before_due():
    body = calendar_service.event_body(
        {"title": "T", "due_at": "2026-10-09T12:00:00", "start_by": "2026-10-09T12:00:00"}
    )
    assert body["start"]["dateTime"] == "2026-10-09T11:30:00Z"


def test_event_body_enforces_a_minimum_block():
    body = calendar_service.event_body(
        {"title": "T", "due_at": "2026-10-09T12:00:00", "start_by": "2026-10-09T11:55:00"}
    )
    assert body["start"]["dateTime"] == "2026-10-09T11:55:00Z"
    assert body["end"]["dateTime"] == "2026-10-09T12:10:00Z"
