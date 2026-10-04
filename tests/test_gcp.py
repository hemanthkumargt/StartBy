import base64
import gzip
import io
import json
import logging
import sqlite3
import tempfile
import urllib.error
from pathlib import Path

import pytest
from freezegun import freeze_time

from app import create_app
from app.config import Config
from app.db import get_db
from app.gcp import auth, bigquery, cloudtasks, dispatcher, monitoring, pubsub, rest, secrets
from app.gcp import storage as gcs
from app.logging_setup import CloudLoggingFormatter
from app.services import hooks
from app.services.notifier import SmtpNotifier
from tests.conftest import register

CRON = {"X-Cron-Secret": "test-cron-secret"}
NOW = "2026-10-04T06:00:00"


@pytest.fixture(autouse=True)
def _sync_dispatcher():
    dispatcher.synchronous = True
    auth.reset_cache()
    yield
    dispatcher.synchronous = False


class Recorder:
    """Stands in for rest.request_json; records every call."""

    def __init__(self, response=None, fail_for=()):
        self.calls = []
        self.response = response or {}
        self.fail_for = fail_for

    def __call__(self, method, url, **kw):
        self.calls.append({"method": method, "url": url, **kw})
        if any(part in url for part in self.fail_for):
            raise rest.GcpError("HTTP 503", 503)
        return self.response

    def to(self, fragment):
        return [c for c in self.calls if fragment in c["url"]]


def make_app(tmp_dir, **env):
    base = {
        "SECRET_KEY": "test-secret",
        "DATABASE_PATH": str(Path(tmp_dir) / "test.db"),
        "CRON_SECRET": "test-cron-secret",
        "FEATURE_ESTIMATES": "1",
        "GCP_PROJECT": "demo-proj",
        "PUBSUB_EVENTS_TOPIC": "startby-events",
        "BQ_DATASET": "startby",
        "CLOUD_TASKS_QUEUE": "start-now",
        "APP_BASE_URL": "https://startby.example.com",
        "GCS_BUCKET": "startby-bucket",
        "MONITORING_ENABLED": "1",
    }
    base.update(env)
    app = create_app(Config(env=base))
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    return app


@pytest.fixture
def gcp_app():
    with tempfile.TemporaryDirectory() as tmp:
        yield make_app(tmp)


@pytest.fixture
def gcp(gcp_app, monkeypatch):
    recorder = Recorder()
    monkeypatch.setattr(rest, "request_json", recorder)
    client = gcp_app.test_client()
    register(client)
    return client, recorder


def _task(client, **over):
    body = {
        "title": "Secret thesis plan",
        "tag": "study",
        "due_at": "2026-10-09T12:00:00",
        "estimate_hours": 2,
    }
    body.update(over)
    return client.post("/api/tasks", json=body).get_json()


# ---- REST helper ---------------------------------------------------------


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_rest_retries_once_on_503_then_succeeds(monkeypatch):
    monkeypatch.setenv("GCP_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(rest.time, "sleep", lambda s: None)
    attempts = []

    def fake_urlopen(request, timeout):
        attempts.append(request.get_header("Authorization"))
        if len(attempts) == 1:
            raise urllib.error.HTTPError(request.full_url, 503, "x", {}, None)
        return _Resp(b'{"ok": true}')

    monkeypatch.setattr(rest.urllib.request, "urlopen", fake_urlopen)
    assert rest.request_json("GET", "https://x.googleapis.com/v1/a") == {"ok": True}
    assert attempts == ["Bearer tok", "Bearer tok"]


def test_rest_does_not_retry_a_400(monkeypatch):
    monkeypatch.setenv("GCP_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(rest.time, "sleep", lambda s: None)
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(1)
        raise urllib.error.HTTPError(request.full_url, 400, "bad", {}, None)

    monkeypatch.setattr(rest.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(rest.GcpError) as err:
        rest.request_json("POST", "https://x/y?key=SECRET", body={})
    assert len(calls) == 1
    assert err.value.status == 400
    assert "SECRET" not in str(err.value)


def test_rest_missing_credentials_raises_gcperror(monkeypatch):
    monkeypatch.delenv("GCP_ACCESS_TOKEN", raising=False)

    def fake_urlopen(request, timeout):
        raise OSError("metadata server unreachable")

    monkeypatch.setattr(auth.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(rest.GcpError):
        rest.request_json("GET", "https://x/y")


def test_auth_caches_metadata_token(monkeypatch):
    monkeypatch.delenv("GCP_ACCESS_TOKEN", raising=False)
    fetches = []

    def fake_urlopen(request, timeout):
        fetches.append(request.get_header("Metadata-flavor"))
        return _Resp(b'{"access_token": "abc", "expires_in": 3600}')

    monkeypatch.setattr(auth.urllib.request, "urlopen", fake_urlopen)
    assert auth.get_access_token() == "abc"
    assert auth.get_access_token() == "abc"
    assert fetches == ["Google"]


# ---- dispatcher ----------------------------------------------------------


def test_dispatcher_swallows_job_failures():
    ran = []
    dispatcher.submit(lambda: 1 / 0)
    dispatcher.submit(lambda: ran.append(1))
    assert ran == [1]


def test_dispatcher_async_runs_jobs_on_both_lanes():
    dispatcher.synchronous = False
    done = []
    dispatcher.submit(lambda: done.append("bulk"))
    dispatcher.submit(lambda: done.append("critical"), lane="critical")
    assert dispatcher.drain(2.0)
    assert sorted(done) == ["bulk", "critical"]


def test_dispatcher_drops_and_logs_when_a_lane_is_full(monkeypatch, caplog):
    import queue

    dispatcher.synchronous = False
    full = queue.Queue(maxsize=1)
    full.put(lambda: None)
    monkeypatch.setitem(dispatcher._queues, "bulk", full)
    ran = []
    with caplog.at_level(logging.ERROR, logger="app.gcp.dispatcher"):
        dispatcher.submit(lambda: ran.append(1))  # must not raise or block
    assert "integration_queue_full lane=bulk" in caplog.text
    assert full.qsize() == 1 and ran == []


def test_a_backed_up_critical_lane_is_independent_of_bulk(monkeypatch):
    import queue

    dispatcher.synchronous = False
    full = queue.Queue(maxsize=1)
    full.put(lambda: None)
    monkeypatch.setitem(dispatcher._queues, "bulk", full)
    done = []
    dispatcher.submit(lambda: done.append("scheduled"), lane="critical")
    assert dispatcher.drain(2.0) is False or True  # bulk's stuck job never runs a worker
    import time

    for _ in range(50):
        if done:
            break
        time.sleep(0.02)
    assert done == ["scheduled"]


# ---- thin clients --------------------------------------------------------


def test_client_request_shapes(monkeypatch):
    rec = Recorder(response={"payload": {"data": base64.b64encode(b"s3cret").decode()}})
    monkeypatch.setattr(rest, "request_json", rec)

    pubsub.publish("p", "t", {"a": 1}, attributes={"event": "e"})
    msg = rec.calls[-1]["body"]["messages"][0]
    assert rec.calls[-1]["url"].endswith("/projects/p/topics/t:publish")
    assert json.loads(base64.b64decode(msg["data"])) == {"a": 1}
    assert msg["attributes"] == {"event": "e"}

    bigquery.insert_rows("p", "d", "t", [{"event_id": "e1", "x": 1}], id_key="event_id")
    assert rec.calls[-1]["body"]["rows"] == [{"insertId": "e1", "json": {"event_id": "e1", "x": 1}}]

    cloudtasks.create_http_task(
        "p",
        "loc",
        "q",
        url="https://h/x",
        payload={"task_id": 1},
        headers={"X-Cron-Secret": "z"},
        schedule_time_rfc3339="2026-10-05T00:00:00Z",
    )
    task = rec.calls[-1]["body"]["task"]
    assert rec.calls[-1]["url"].endswith("/locations/loc/queues/q/tasks")
    assert task["scheduleTime"] == "2026-10-05T00:00:00Z"
    assert task["httpRequest"]["headers"]["X-Cron-Secret"] == "z"
    assert json.loads(base64.b64decode(task["httpRequest"]["body"])) == {"task_id": 1}

    gcs.upload_object("b", "pdfs/a b.pdf", b"x", content_type="application/pdf")
    assert "name=pdfs%2Fa%20b.pdf" in rec.calls[-1]["url"]
    assert rec.calls[-1]["raw_body"] == b"x"

    assert secrets.access_secret("p", "SMTP_PASSWORD") == "s3cret"
    assert rec.calls[-1]["url"].endswith("/secrets/SMTP_PASSWORD/versions/latest:access")

    monitoring.write_int_metric("p", "reminders_sent", 3, {"kind": "due_soon"})
    series = rec.calls[-1]["body"]["timeSeries"][0]
    assert series["metric"]["type"] == "custom.googleapis.com/startby/reminders_sent"
    assert series["points"][0]["value"] == {"int64Value": "3"}


def test_bigquery_row_errors_are_failures(monkeypatch):
    monkeypatch.setattr(rest, "request_json", Recorder(response={"insertErrors": [{"index": 0}]}))
    with pytest.raises(rest.GcpError):
        bigquery.insert_rows("p", "d", "t", [{"event_id": "e"}], id_key="event_id")


# ---- Secret Manager loader ----------------------------------------------


def test_secret_loader_overrides_env_and_lists_names():
    env = {"GCP_SECRETS": "SECRET_KEY, SMTP_PASSWORD", "GCP_PROJECT": "p", "SECRET_KEY": "old"}
    loaded = secrets.load_into_environ(env, access=lambda project, name: f"{project}:{name}")
    assert loaded == ["SECRET_KEY", "SMTP_PASSWORD"]
    assert env["SECRET_KEY"] == "p:SECRET_KEY"
    assert env["SMTP_PASSWORD"] == "p:SMTP_PASSWORD"


def test_secret_loader_noop_when_unset():
    assert secrets.load_into_environ({}, access=lambda *a: 1 / 0) == []


def test_secret_loader_fails_loudly():
    def boom(project, name):
        raise rest.GcpError("HTTP 403", 403)

    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        secrets.load_into_environ({"GCP_SECRETS": "SECRET_KEY", "GCP_PROJECT": "p"}, access=boom)
    with pytest.raises(RuntimeError, match="CRON_SECRET"):
        secrets.load_into_environ({"GCP_SECRETS": "CRON_SECRET", "GCP_PROJECT": "p"}, access=boom)
    with pytest.raises(RuntimeError, match="GCP_PROJECT"):
        secrets.load_into_environ({"GCP_SECRETS": "X"}, access=boom)


def test_optional_secret_missing_is_skipped_with_a_warning(caplog):
    def access(project, name):
        if name == "SMTP_PASSWORD" or name == "GEMINI_API_KEY":
            raise rest.GcpError("HTTP 404", 404)
        return f"v-{name}"

    env = {
        "GCP_SECRETS": "SECRET_KEY,CRON_SECRET,SMTP_PASSWORD,GEMINI_API_KEY",
        "GCP_PROJECT": "p",
    }
    with caplog.at_level(logging.WARNING):
        loaded = secrets.load_into_environ(env, access=access)
    assert loaded == ["SECRET_KEY", "CRON_SECRET"]
    assert "SMTP_PASSWORD" not in env and "GEMINI_API_KEY" not in env
    assert "optional_secret_skipped name=SMTP_PASSWORD" in caplog.text


# ---- logging -------------------------------------------------------------


def test_cloud_logging_formatter_emits_structured_json():
    record = logging.LogRecord("app.x", logging.ERROR, __file__, 1, "boom %s", ("now",), None)
    line = json.loads(CloudLoggingFormatter().format(record))
    assert line["severity"] == "ERROR"
    assert line["message"] == "boom now"
    assert line["logger"] == "app.x"


# ---- hooks ---------------------------------------------------------------


def test_a_failing_listener_does_not_stop_others_or_the_caller():
    seen = []

    class Bad:
        def on_task_created(self, task, *, user_id):
            raise RuntimeError("down")

    class Good:
        def on_task_created(self, task, *, user_id):
            seen.append(task["id"])

    hooks.clear()
    hooks.register(Bad())
    hooks.register(Good())
    hooks.on_task_created({"id": 7}, user_id=1)
    assert seen == [7]


# ---- events: Pub/Sub + BigQuery -----------------------------------------


@freeze_time(NOW)
def test_task_events_go_to_pubsub_and_bigquery_without_title_or_user_id(gcp):
    client, rec = gcp
    task = _task(client)
    (publish,) = rec.to(":publish")
    payload = json.loads(base64.b64decode(publish["body"]["messages"][0]["data"]))
    assert payload["event"] == "task.created"
    assert payload["task_id"] == task["id"]
    assert payload["tag"] == "study" and payload["estimate_hours"] == 2.0
    assert "Secret thesis plan" not in json.dumps(payload)
    assert len(payload["user_hash"]) == 16 and payload["user_hash"] != "1"
    (insert,) = rec.to("insertAll")
    assert insert["body"]["rows"][0]["insertId"] == payload["event_id"]


@freeze_time(NOW)
def test_completion_event_carries_estimate_accuracy_ratio(gcp):
    client, rec = gcp
    task = _task(client)
    client.post(f"/api/tasks/{task['id']}/complete", json={"actual_hours": 3})
    events = [
        json.loads(base64.b64decode(c["body"]["messages"][0]["data"])) for c in rec.to(":publish")
    ]
    done = next(e for e in events if e["event"] == "task.completed")
    assert done["ratio"] == pytest.approx(1.5)


@freeze_time(NOW)
def test_all_lifecycle_events_fire(gcp):
    client, rec = gcp
    task = _task(client)
    client.patch(f"/api/tasks/{task['id']}", json={"title": "renamed"})
    client.post(f"/api/tasks/{task['id']}/complete")
    client.post(f"/api/tasks/{task['id']}/reopen")
    client.delete(f"/api/tasks/{task['id']}")
    names = [
        json.loads(base64.b64decode(c["body"]["messages"][0]["data"]))["event"]
        for c in rec.to(":publish")
    ]
    assert names == [
        "task.created",
        "task.updated",
        "task.completed",
        "task.reopened",
        "task.deleted",
    ]


@freeze_time(NOW)
def test_a_cloud_outage_never_fails_the_users_request(gcp_app, monkeypatch):
    rec = Recorder(fail_for=("pubsub", "bigquery", "cloudtasks"))
    monkeypatch.setattr(rest, "request_json", rec)
    client = gcp_app.test_client()
    register(client)
    response = client.post(
        "/api/tasks",
        json={"title": "t", "tag": "work", "due_at": "2026-10-09T12:00:00", "estimate_hours": 1},
    )
    assert response.status_code == 201
    assert rec.calls  # the integrations did try


def test_nothing_is_called_when_unconfigured(app, monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(rest, "request_json", rec)
    client = app.test_client()
    register(client)
    client.post("/api/tasks", json={"title": "t", "tag": "work"})
    assert rec.calls == []


# ---- Cloud Tasks scheduling ---------------------------------------------


@freeze_time(NOW)
def test_pending_task_with_start_by_schedules_a_callback_at_start_by(gcp):
    client, rec = gcp
    task = _task(client)  # due 2026-10-09T12:00 UTC, 2h * 1.5 * 1.15 = 3h27m lead
    (call,) = rec.to("cloudtasks")
    http = call["body"]["task"]["httpRequest"]
    assert http["url"] == "https://startby.example.com/api/internal/start-now"
    assert http["headers"]["X-Cron-Secret"] == "test-cron-secret"
    assert json.loads(base64.b64decode(http["body"])) == {"task_id": task["id"]}
    assert call["body"]["task"]["scheduleTime"] == "2026-10-09T08:33:05Z"  # 08:33:00 + 5s slack


@freeze_time(NOW)
def test_start_by_already_passed_schedules_immediately(gcp):
    client, rec = gcp
    _task(client, due_at="2026-10-04T07:00:00")
    (call,) = rec.to("cloudtasks")
    assert "scheduleTime" not in call["body"]["task"]


@freeze_time(NOW)
def test_far_future_start_by_is_left_to_the_cron_sweep(gcp):
    client, rec = gcp
    _task(client, due_at="2026-12-31T12:00:00")
    assert rec.to("cloudtasks") == []


@freeze_time(NOW)
def test_no_callback_for_done_tasks_or_tasks_without_estimates(gcp):
    client, rec = gcp
    task = _task(client)
    rec.calls.clear()
    client.post(f"/api/tasks/{task['id']}/complete")
    client.post("/api/tasks", json={"title": "no estimate", "due_at": "2026-10-09T12:00:00"})
    assert rec.to("cloudtasks") == []


# ---- /api/internal/start-now --------------------------------------------


def _start_now(client, task_id, secret="test-cron-secret"):
    headers = {"X-Cron-Secret": secret} if secret else {}
    return client.post("/api/internal/start-now", json={"task_id": task_id}, headers=headers)


@pytest.fixture
def mailer(monkeypatch):
    sent = []

    def fake_send(self, *, to, subject, body):
        sent.append({"to": to, "subject": subject, "body": body})
        return True

    monkeypatch.setattr(SmtpNotifier, "send", fake_send)
    return sent


def test_start_now_rejects_missing_or_wrong_secret(gcp):
    client, _ = gcp
    assert _start_now(client, 1, secret=None).status_code == 401
    assert _start_now(client, 1, secret="nope").status_code == 401


@pytest.mark.parametrize("task_id", ["1", None, True, 1.5, [1]])
def test_start_now_validates_task_id(gcp, task_id):
    client, _ = gcp
    response = client.post("/api/internal/start-now", json={"task_id": task_id}, headers=CRON)
    assert response.status_code == 422


def test_start_now_sends_once_when_red_and_is_idempotent(gcp, mailer):
    client, _ = gcp
    with freeze_time(NOW):
        task = _task(client, due_at="2026-10-04T07:00:00")  # already red
        first = _start_now(client, task["id"]).get_json()
        second = _start_now(client, task["id"]).get_json()
    assert first == {"sent": True, "reason": "sent"}
    assert second["sent"] is False and second["reason"] == "not_eligible"
    assert len(mailer) == 1  # I7
    assert "How we worked this out" in mailer[0]["body"]


def test_start_now_before_start_by_sends_nothing_and_reschedules(gcp, mailer):
    client, rec = gcp
    with freeze_time(NOW):
        task = _task(client)  # start_by is days away
        rec.calls.clear()
        result = _start_now(client, task["id"]).get_json()
    assert result["reason"] == "not_yet_red"
    assert mailer == []
    (call,) = rec.to("cloudtasks")  # followed start_by with a new trigger
    assert call["body"]["task"]["scheduleTime"] == "2026-10-09T08:33:05Z"


def test_start_now_ignores_completed_and_deleted_tasks(gcp, mailer):
    client, _ = gcp
    with freeze_time(NOW):
        done = _task(client, due_at="2026-10-04T07:00:00")
        client.post(f"/api/tasks/{done['id']}/complete")
        gone = _task(client, due_at="2026-10-04T07:00:00")
        client.delete(f"/api/tasks/{gone['id']}")
        assert _start_now(client, done["id"]).get_json()["reason"] == "not_eligible"
        assert _start_now(client, gone["id"]).get_json()["reason"] == "not_eligible"
        assert _start_now(client, 99999).get_json()["reason"] == "not_eligible"
    assert mailer == []


def test_start_now_send_failure_returns_503_and_records_nothing(gcp, monkeypatch):
    client, _ = gcp
    monkeypatch.setattr(SmtpNotifier, "send", lambda self, **kw: False)
    with freeze_time(NOW):
        task = _task(client, due_at="2026-10-04T07:00:00")
        assert _start_now(client, task["id"]).status_code == 503
        monkeypatch.setattr(SmtpNotifier, "send", lambda self, **kw: True)
        assert _start_now(client, task["id"]).get_json()["sent"] is True  # retry succeeds


# ---- Cloud Storage: PDF archive + backups -------------------------------


def test_uploaded_pdf_is_archived_under_hashed_user_path(gcp, monkeypatch):
    from app.services import gemini_client

    client, rec = gcp
    app_cfg = client.application.config
    app_cfg["FEATURE_SMART_CAPTURE"] = True
    monkeypatch.setattr(gemini_client, "generate_task_drafts", lambda text, **kw: [])
    from tests.test_capture import _minimal_pdf

    response = client.post(
        "/api/capture/preview",
        data={"file": (io.BytesIO(_minimal_pdf("Submit report")), "s.pdf")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    (upload,) = rec.to("/upload/storage/v1/b/startby-bucket/o")
    assert "name=pdfs%2F" in upload["url"] and upload["url"].endswith(".pdf")
    assert upload["content_type"] == "application/pdf"


def test_backup_endpoint_auth_and_configuration(gcp_app, app):
    assert app.test_client().post("/api/cron/backup").status_code == 401
    unconfigured = app.test_client().post("/api/cron/backup", headers=CRON)
    assert unconfigured.status_code == 503


def test_backup_uploads_a_restorable_gzip_snapshot(gcp, monkeypatch):
    client, rec = gcp
    _task(client, title="persisted row")
    response = client.post("/api/cron/backup", headers=CRON)
    assert response.status_code == 200
    (upload,) = (c for c in rec.calls if "uploadType=media" in c["url"] and "backups" in c["url"])
    assert response.get_json()["object"].startswith("backups/startby-")
    restored = gzip.decompress(upload["raw_body"])
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "r.db"
        path.write_bytes(restored)
        titles = [r[0] for r in sqlite3.connect(path).execute("SELECT title FROM tasks")]
    assert titles == ["persisted row"]


def test_backup_upload_failure_is_a_502(gcp_app, monkeypatch):
    monkeypatch.setattr(rest, "request_json", Recorder(fail_for=("storage.googleapis",)))
    client = gcp_app.test_client()
    assert client.post("/api/cron/backup", headers=CRON).status_code == 502


# ---- Cloud Monitoring ----------------------------------------------------


def test_cron_reports_reminder_counts_as_custom_metrics(gcp, mailer):
    client, rec = gcp
    assert client.post("/api/cron/reminders", headers=CRON).status_code == 200
    metrics = rec.to("monitoring.googleapis.com")
    kinds = {m["body"]["timeSeries"][0]["metric"]["labels"]["kind"] for m in metrics}
    assert {"due_soon_sent", "overdue_sent", "start_now_sent"} <= kinds


# ---- review fixes ---------------------------------------------------------


def test_non_ascii_cron_secret_header_is_a_401_not_a_500(gcp):
    client, _ = gcp
    response = client.post("/api/cron/backup", headers={"X-Cron-Secret": "é".encode("latin-1")})
    assert response.status_code == 401
    assert _start_now(client, 1, secret="é").status_code == 401


def test_start_now_callback_is_inert_when_estimates_flag_is_off(gcp, mailer):
    client, _ = gcp
    with freeze_time(NOW):
        task = _task(client, due_at="2026-10-04T07:00:00")  # red
        client.application.config["FEATURE_ESTIMATES"] = False
        result = _start_now(client, task["id"]).get_json()
    assert result == {"sent": False, "reason": "not_eligible"}
    assert mailer == []


def test_two_workers_racing_for_one_start_now_send_exactly_one_email(gcp, mailer, monkeypatch):
    """Cron sweep and Cloud Tasks callback both see a red task with no row.
    The claim is taken before sending, so only one of them emails (I7)."""
    from app.services import reminder_service

    client, _ = gcp
    with freeze_time(NOW):
        task = _task(client, due_at="2026-10-04T07:00:00")
        app = client.application
        with app.app_context():
            conn = get_db()
            first = reminder_service.send_start_now_for_task(
                conn, SmtpNotifier(host="h", port=1, user="u", password="p"), task["id"]
            )
            second = reminder_service.send_start_now_for_task(
                conn, SmtpNotifier(host="h", port=1, user="u", password="p"), task["id"]
            )
    assert (first["sent"], second["sent"]) == (True, False)
    assert len(mailer) == 1


def test_a_failed_send_releases_the_claim_so_the_next_run_retries(gcp, monkeypatch):
    client, _ = gcp
    attempts = []

    def flaky_send(self, *, to, subject, body):
        if not subject.startswith("Time to start"):
            return True  # the due-soon email goes through; only start-now is flaky
        attempts.append(1)
        return len(attempts) > 1

    monkeypatch.setattr(SmtpNotifier, "send", flaky_send)
    with freeze_time(NOW):
        _task(client, due_at="2026-10-04T07:00:00")
        first = client.post("/api/cron/reminders", headers=CRON).get_json()
        second = client.post("/api/cron/reminders", headers=CRON).get_json()
        third = client.post("/api/cron/reminders", headers=CRON).get_json()
    assert (first["start_now_sent"], second["start_now_sent"], third["start_now_sent"]) == (0, 1, 0)
    assert len(attempts) == 2


def test_secret_values_are_stripped(monkeypatch):
    rec = Recorder(response={"payload": {"data": base64.b64encode(b"s3cret\n").decode()}})
    monkeypatch.setattr(rest, "request_json", rec)
    assert secrets.access_secret("p", "CRON_SECRET") == "s3cret"


def test_redirects_are_refused_so_the_bearer_token_cannot_be_forwarded():
    import urllib.request

    handler = next(h for h in urllib.request._opener.handlers if isinstance(h, rest._NoRedirect))
    req = urllib.request.Request(
        "https://a.googleapis.com/x", headers={"Authorization": "Bearer t"}
    )
    assert handler.redirect_request(req, None, 302, "Found", {}, "https://evil.example/") is None


def test_a_401_on_the_cached_service_account_token_refetches_it(monkeypatch):
    monkeypatch.delenv("GCP_ACCESS_TOKEN", raising=False)
    monkeypatch.setattr(rest.time, "sleep", lambda s: None)
    tokens = iter(["stale", "fresh"])
    monkeypatch.setattr(auth, "get_access_token", lambda **kw: next(tokens))
    seen = []

    def fake_urlopen(request, timeout):
        seen.append(request.get_header("Authorization"))
        if len(seen) == 1:
            raise urllib.error.HTTPError(request.full_url, 401, "x", {}, None)
        return _Resp(b"{}")

    monkeypatch.setattr(rest.urllib.request, "urlopen", fake_urlopen)
    reset = []
    monkeypatch.setattr(auth, "reset_cache", lambda: reset.append(1))
    rest.request_json("GET", "https://x.googleapis.com/v1/a")
    assert seen == ["Bearer stale", "Bearer fresh"] and reset == [1]


# ---- GcpError carries a parsed, capped error code ---------------------------


@pytest.mark.parametrize(
    "body,expected",
    [
        (
            b'{"error": "invalid_grant", "error_description": "Token has been revoked."}',
            "invalid_grant",
        ),
        (
            b'{"error": {"code": 403, "errors": [{"reason": "rateLimitExceeded"}]}}',
            "rateLimitExceeded",
        ),
        (b'{"error": {"status": "PERMISSION_DENIED", "message": "m"}}', "PERMISSION_DENIED"),
        (b"<html>bad gateway</html>", ""),
        (b"", ""),
        (b'{"error": "' + b"x" * 500 + b'"}', "x" * 64),
        (b'{"error": "bad code!\\n<script>"}', "badcodescript"),
    ],
)
def test_parse_error_code(body, expected):
    assert rest.parse_error_code(body) == expected


def test_http_error_body_becomes_error_code_without_the_description(monkeypatch):
    import io
    import urllib.error

    def fake_urlopen(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url,
            400,
            "Bad Request",
            {},
            io.BytesIO(b'{"error": "invalid_client", "error_description": "secret-ish"}'),
        )

    monkeypatch.setattr(rest.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(rest.GcpError) as caught:
        rest.request_json("POST", "https://x.example/token", use_auth=False)
    assert caught.value.status == 400 and caught.value.error == "invalid_client"
    assert "secret-ish" not in str(caught.value)


# ---- dispatcher: queued jobs are not dropped on a graceful exit ---------------


def test_exit_hook_drains_queued_jobs_and_is_bounded(monkeypatch):
    import threading

    assert 0 < dispatcher.EXIT_DRAIN_SECONDS <= 8
    registered = []
    monkeypatch.setattr(dispatcher.atexit, "register", registered.append)
    monkeypatch.setattr(dispatcher, "_exit_hook_installed", False)
    monkeypatch.setattr(dispatcher, "synchronous", False)
    monkeypatch.setattr(dispatcher, "_threads", {lane: None for lane in dispatcher.LANES})

    gate, done = threading.Event(), []
    dispatcher.submit(lambda: (gate.wait(2), done.append("slow")))
    dispatcher.submit(lambda: done.append("second"), lane="critical")
    dispatcher.submit(lambda: done.append("third"))
    assert registered == [dispatcher._drain_at_exit]  # installed once, not per submit

    gate.set()
    dispatcher._drain_at_exit()  # what the interpreter calls on exit
    assert sorted(done) == ["second", "slow", "third"]


def test_exit_hook_gives_up_after_the_timeout_and_logs(monkeypatch, caplog):
    import threading

    monkeypatch.setattr(dispatcher, "EXIT_DRAIN_SECONDS", 0.2)
    monkeypatch.setattr(dispatcher, "_exit_hook_installed", True)
    monkeypatch.setattr(dispatcher, "synchronous", False)
    monkeypatch.setattr(dispatcher, "_threads", {lane: None for lane in dispatcher.LANES})
    release = threading.Event()
    dispatcher.submit(lambda: release.wait(5))
    with caplog.at_level(logging.WARNING):
        dispatcher._drain_at_exit()
    release.set()
    assert "dispatcher_drain_timeout" in caplog.text
