from freezegun import freeze_time

from app.db import get_db
from app.services import reminder_service
from app.services.notifier import SmtpNotifier
from tests.conftest import register

CRON_HEADERS = {"X-Cron-Secret": "test-cron-secret"}


def create_task(client, **overrides):
    body = {"title": "Submit assignment", "tag": "study"}
    body.update(overrides)
    return client.post("/api/tasks", json=body)


def test_cron_rejects_missing_secret(client):
    response = client.post("/api/cron/reminders")
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "unauthorized"


def test_cron_rejects_wrong_secret(client):
    response = client.post("/api/cron/reminders", headers={"X-Cron-Secret": "nope"})
    assert response.status_code == 401


def test_cron_with_no_eligible_tasks_sends_nothing(client, monkeypatch):
    monkeypatch.setattr(SmtpNotifier, "send", lambda self, **kw: True)
    register(client)
    response = client.post("/api/cron/reminders", headers=CRON_HEADERS)
    assert response.status_code == 200
    assert response.get_json() == {"due_soon_sent": 0, "overdue_sent": 0}


@freeze_time("2026-10-03T12:00:00")
def test_I7_due_soon_reminder_sent_exactly_once_across_repeated_cron_runs(client, monkeypatch):
    monkeypatch.setattr(SmtpNotifier, "send", lambda self, **kw: True)
    register(client)
    create_task(client, due_at="2026-10-03T18:00:00")  # 6h away, inside the 24h window

    first = client.post("/api/cron/reminders", headers=CRON_HEADERS).get_json()
    second = client.post("/api/cron/reminders", headers=CRON_HEADERS).get_json()
    third = client.post("/api/cron/reminders", headers=CRON_HEADERS).get_json()

    assert first["due_soon_sent"] == 1
    assert second["due_soon_sent"] == 0
    assert third["due_soon_sent"] == 0


@freeze_time("2026-10-03T12:00:00")
def test_I7_overdue_reminder_sent_exactly_once_across_repeated_cron_runs(client, monkeypatch):
    monkeypatch.setattr(SmtpNotifier, "send", lambda self, **kw: True)
    register(client)
    create_task(client, due_at="2026-10-01T09:00:00")  # already in the past

    first = client.post("/api/cron/reminders", headers=CRON_HEADERS).get_json()
    second = client.post("/api/cron/reminders", headers=CRON_HEADERS).get_json()

    assert first["overdue_sent"] == 1
    assert second["overdue_sent"] == 0


@freeze_time("2026-10-03T12:00:00")
def test_I8_moving_due_date_allows_a_new_due_soon_reminder(client, monkeypatch):
    monkeypatch.setattr(SmtpNotifier, "send", lambda self, **kw: True)
    register(client)
    task = create_task(client, due_at="2026-10-03T18:00:00").get_json()

    first = client.post("/api/cron/reminders", headers=CRON_HEADERS).get_json()
    assert first["due_soon_sent"] == 1

    # move the deadline further out, still inside the window — should remind again
    client.patch(f"/api/tasks/{task['id']}", json={"due_at": "2026-10-04T08:00:00"})

    second = client.post("/api/cron/reminders", headers=CRON_HEADERS).get_json()
    assert second["due_soon_sent"] == 1


@freeze_time("2026-10-03T12:00:00")
def test_I8_reopening_a_still_overdue_task_allows_a_new_overdue_reminder(client, monkeypatch):
    """Regression guard: reopen_task() used to skip the reminders_sent
    clear that update_task() does for due_at changes, so a task that went
    overdue -> reminded -> completed -> reopened (still overdue) could
    never be reminded about again."""
    monkeypatch.setattr(SmtpNotifier, "send", lambda self, **kw: True)
    register(client)
    task = create_task(client, due_at="2026-10-01T09:00:00").get_json()  # already overdue

    first = client.post("/api/cron/reminders", headers=CRON_HEADERS).get_json()
    assert first["overdue_sent"] == 1

    client.post(f"/api/tasks/{task['id']}/complete")
    client.post(f"/api/tasks/{task['id']}/reopen")

    second = client.post("/api/cron/reminders", headers=CRON_HEADERS).get_json()
    assert second["overdue_sent"] == 1


@freeze_time("2026-10-03T12:00:00")
def test_smtp_failure_is_not_recorded_as_sent_and_retries_next_run(client, monkeypatch):
    register(client)
    create_task(client, due_at="2026-10-03T18:00:00")

    monkeypatch.setattr(SmtpNotifier, "send", lambda self, **kw: False)
    down = client.post("/api/cron/reminders", headers=CRON_HEADERS).get_json()
    assert down["due_soon_sent"] == 0

    monkeypatch.setattr(SmtpNotifier, "send", lambda self, **kw: True)
    recovered = client.post("/api/cron/reminders", headers=CRON_HEADERS).get_json()
    assert recovered["due_soon_sent"] == 1


@freeze_time("2026-10-03T12:00:00")
def test_deleted_task_is_never_reminded(client, monkeypatch):
    monkeypatch.setattr(SmtpNotifier, "send", lambda self, **kw: True)
    register(client)
    task = create_task(client, due_at="2026-10-03T18:00:00").get_json()
    client.delete(f"/api/tasks/{task['id']}")

    result = client.post("/api/cron/reminders", headers=CRON_HEADERS).get_json()
    assert result == {"due_soon_sent": 0, "overdue_sent": 0}


@freeze_time("2026-10-03T12:00:00")
def test_run_reminders_respects_max_per_run_budget(app, monkeypatch):
    monkeypatch.setattr(SmtpNotifier, "send", lambda self, **kw: True)
    with app.test_client() as client:
        register(client)
        create_task(client, title="First", due_at="2026-10-03T13:00:00")
        create_task(client, title="Second", due_at="2026-10-03T14:00:00")

        with app.app_context():
            from app.services.notifier import get_notifier

            conn = get_db()
            counts = reminder_service.run_reminders(
                conn, get_notifier(app.config), now_iso="2026-10-03T12:00:00", max_per_run=1
            )
    assert counts["due_soon_sent"] == 1
