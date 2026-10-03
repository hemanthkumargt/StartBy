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


@freeze_time("2026-10-10T15:00:00")
def test_I7_start_now_reminder_sent_exactly_once_across_repeated_cron_runs(
    estimates_client, monkeypatch
):
    monkeypatch.setattr(SmtpNotifier, "send", lambda self, **kw: True)
    register(estimates_client)
    # 2h estimate, default 1.5x multiplier, 15% buffer -> start_by is
    # 2026-10-10T14:33:00 for this due_at; already passed at the frozen time.
    create_task(estimates_client, due_at="2026-10-10T18:00:00", estimate_hours=2.0)

    first = estimates_client.post("/api/cron/reminders", headers=CRON_HEADERS).get_json()
    second = estimates_client.post("/api/cron/reminders", headers=CRON_HEADERS).get_json()

    assert first["start_now_sent"] == 1
    assert second["start_now_sent"] == 0


@freeze_time("2026-10-10T12:00:00")
def test_start_now_reminder_is_not_sent_before_start_by(estimates_client, monkeypatch):
    monkeypatch.setattr(SmtpNotifier, "send", lambda self, **kw: True)
    register(estimates_client)
    # Due in 60 days: start_by is comfortably in the future (green), not red.
    create_task(estimates_client, due_at="2026-12-25T18:00:00", estimate_hours=2.0)

    result = estimates_client.post("/api/cron/reminders", headers=CRON_HEADERS).get_json()
    assert result["start_now_sent"] == 0


def test_I15_flag_off_cron_response_has_no_start_now_sent_key(client, monkeypatch):
    monkeypatch.setattr(SmtpNotifier, "send", lambda self, **kw: True)
    register(client)
    create_task(client, due_at="2026-10-10T18:00:00")

    result = client.post("/api/cron/reminders", headers=CRON_HEADERS).get_json()
    assert "start_now_sent" not in result


@freeze_time("2026-10-10T15:00:00")
def test_I8_moving_due_date_allows_a_new_start_now_reminder(estimates_client, monkeypatch):
    monkeypatch.setattr(SmtpNotifier, "send", lambda self, **kw: True)
    register(estimates_client)
    task = create_task(
        estimates_client, due_at="2026-10-10T18:00:00", estimate_hours=2.0
    ).get_json()

    first = estimates_client.post("/api/cron/reminders", headers=CRON_HEADERS).get_json()
    assert first["start_now_sent"] == 1

    # Push the deadline out, then back into "already past start_by" again —
    # should be able to remind about the new start_by too.
    estimates_client.patch(f"/api/tasks/{task['id']}", json={"due_at": "2026-12-25T18:00:00"})
    estimates_client.patch(f"/api/tasks/{task['id']}", json={"due_at": "2026-10-10T18:00:00"})

    second = estimates_client.post("/api/cron/reminders", headers=CRON_HEADERS).get_json()
    assert second["start_now_sent"] == 1


@freeze_time("2026-10-10T15:00:00")
def test_I8_changing_estimate_alone_allows_a_new_start_now_reminder(estimates_client, monkeypatch):
    """I10: start_by depends on estimate_hours as much as due_at, so an
    estimate-only edit (due_at untouched) that moves start_by must also be
    able to clear an old start_now reminder, same as a due_at edit does."""
    monkeypatch.setattr(SmtpNotifier, "send", lambda self, **kw: True)
    register(estimates_client)
    task = create_task(
        estimates_client, due_at="2026-10-10T18:00:00", estimate_hours=2.0
    ).get_json()

    first = estimates_client.post("/api/cron/reminders", headers=CRON_HEADERS).get_json()
    assert first["start_now_sent"] == 1

    # Shrink the estimate so start_by moves back into the future (not red),
    # then restore it — due_at is never touched, only estimate_hours.
    estimates_client.patch(f"/api/tasks/{task['id']}", json={"estimate_hours": 0.25})
    estimates_client.patch(f"/api/tasks/{task['id']}", json={"estimate_hours": 2.0})

    second = estimates_client.post("/api/cron/reminders", headers=CRON_HEADERS).get_json()
    assert second["start_now_sent"] == 1


def test_I13_start_now_reminder_uses_the_learned_multiplier_not_the_cold_start_default(
    estimates_client, monkeypatch
):
    """Regression guard: reminder_service must agree with the
    dashboard/task API about whether a task is actually red. Builds the
    same tag history as the I13 worked example (ratios 2.0/2.5/2.0 ->
    1.718x), then freezes time at a point that is RED under that learned
    multiplier but only AMBER under the 1.5x cold-start default -- if
    reminder_service were still using the default, no reminder would fire
    here."""
    monkeypatch.setattr(SmtpNotifier, "send", lambda self, **kw: True)
    with freeze_time("2026-10-01T00:00:00"):
        register(estimates_client)
        for estimate, actual in [(1.0, 2.0), (2.0, 5.0), (3.0, 6.0)]:
            t = create_task(estimates_client, estimate_hours=estimate).get_json()
            estimates_client.post(f"/api/tasks/{t['id']}/complete", json={"actual_hours": actual})

    with freeze_time("2026-10-10T14:15:00"):
        task = create_task(
            estimates_client, estimate_hours=2.0, due_at="2026-10-10T18:00:00"
        ).get_json()
        # Learned multiplier (~1.718x) -> start_by ~14:02:53, already past.
        assert task["risk"] == "red"
        # The 1.5x cold-start default would give 14:33:00, not yet passed.

        result = estimates_client.post("/api/cron/reminders", headers=CRON_HEADERS).get_json()
        assert result["start_now_sent"] == 1


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
