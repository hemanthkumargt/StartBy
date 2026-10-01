import re

from freezegun import freeze_time

from tests.conftest import register

ISO_T_FORMAT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")


def create_task(client, **overrides):
    body = {"title": "Finish DBMS report", "tag": "study"}
    body.update(overrides)
    return client.post("/api/tasks", json=body)


def test_create_task_happy_path(client):
    register(client)
    response = create_task(client)
    assert response.status_code == 201
    task = response.get_json()
    assert task["title"] == "Finish DBMS report"
    assert task["tag"] == "study"
    assert task["status"] == "pending"
    assert task["is_overdue"] is False
    assert task["completed_at"] is None


def test_create_task_timestamps_use_the_shared_iso_format(client):
    """Regression guard: created_at must use the same T-separated format as
    every other app-generated timestamp (timeutil.utcnow_iso), not SQLite's
    own space-separated datetime('now') default."""
    register(client)
    task = create_task(client).get_json()
    assert ISO_T_FORMAT.match(task["created_at"])
    assert ISO_T_FORMAT.match(task["updated_at"])

    completed = client.post(f"/api/tasks/{task['id']}/complete").get_json()
    assert ISO_T_FORMAT.match(completed["completed_at"])
    assert ISO_T_FORMAT.match(completed["updated_at"])

    activity = client.get("/api/activity").get_json()
    assert all(ISO_T_FORMAT.match(a["at"]) for a in activity)


def test_create_task_defaults_tag_to_personal(client):
    register(client)
    response = create_task(client, tag=None)
    assert response.get_json()["tag"] == "personal"


def test_create_task_rejects_empty_title(client):
    register(client)
    response = create_task(client, title="  ")
    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "validation"


def test_create_task_rejects_title_over_200_chars(client):
    register(client)
    response = create_task(client, title="x" * 201)
    assert response.status_code == 422


def test_create_task_rejects_unknown_tag(client):
    register(client)
    response = create_task(client, tag="hobby")
    assert response.status_code == 422


def test_create_task_logs_one_activity_row(client):
    register(client)
    create_task(client)
    activity = client.get("/api/activity").get_json()
    assert len(activity) == 1
    assert activity[0]["action"] == "created"


def test_create_task_validation_failure_logs_nothing(client):
    register(client)
    create_task(client, title="")
    activity = client.get("/api/activity").get_json()
    assert activity == []


# --- I1: a user can only read or change their own tasks and activity ---


def test_I1_other_users_task_is_404_everywhere(client):
    register(client, email="alice@example.com")
    task_id = create_task(client).get_json()["id"]
    client.post("/api/auth/logout")

    register(client, email="bob@example.com")
    assert client.get(f"/api/tasks/{task_id}").status_code == 404
    assert client.patch(f"/api/tasks/{task_id}", json={"title": "hijacked"}).status_code == 404
    assert client.post(f"/api/tasks/{task_id}/complete").status_code == 404
    assert client.post(f"/api/tasks/{task_id}/reopen").status_code == 404
    assert client.delete(f"/api/tasks/{task_id}").status_code == 404


def test_I1_activity_feed_is_per_user(client):
    register(client, email="alice@example.com")
    create_task(client, title="Alice task")
    client.post("/api/auth/logout")

    register(client, email="bob@example.com")
    activity = client.get("/api/activity").get_json()
    assert activity == []


# --- I2: soft-deleted tasks never appear in lists, counts, dashboard, activity query ---


def test_I2_deleted_task_disappears_from_every_read(client):
    register(client)
    task_id = create_task(client).get_json()["id"]

    assert client.delete(f"/api/tasks/{task_id}").status_code == 204

    assert client.get(f"/api/tasks/{task_id}").status_code == 404
    assert client.get("/api/tasks").get_json() == []

    dashboard = client.get("/api/dashboard").get_json()
    assert dashboard["total"] == 0
    assert dashboard["due_next"] == []

    # deleting again is a 404, not a second soft delete
    assert client.delete(f"/api/tasks/{task_id}").status_code == 404


def test_I2_delete_logs_exactly_one_activity_row(client):
    register(client)
    task_id = create_task(client).get_json()["id"]
    client.delete(f"/api/tasks/{task_id}")
    activity = client.get("/api/activity").get_json()
    actions = [a["action"] for a in activity]
    assert actions.count("deleted") == 1


# --- I3: total = completed + pending, overdue subset of pending ---


def test_I3_counts_consistent_over_mixed_tasks(client):
    register(client)
    t1 = create_task(
        client, title="Pending with future due", due_at="2030-01-01T00:00:00"
    ).get_json()
    create_task(client, title="Pending no due date")
    t3 = create_task(client, title="Will be completed").get_json()
    client.post(f"/api/tasks/{t3['id']}/complete")

    dashboard = client.get("/api/dashboard").get_json()
    assert dashboard["total"] == 3
    assert dashboard["completed"] == 1
    assert dashboard["pending"] == 2
    assert dashboard["total"] == dashboard["completed"] + dashboard["pending"]
    assert dashboard["overdue"] <= dashboard["pending"]
    assert dashboard["overdue"] == 0
    assert t1["id"]  # keep reference, avoid unused-var lint


# --- I4: overdue = pending AND due_at < now (UTC); done/no-due-date never overdue ---


@freeze_time("2026-10-03T12:00:00")
def test_I4_overdue_boundary_one_second_in_past_is_overdue(client):
    register(client)
    task = create_task(client, due_at="2026-10-03T11:59:59").get_json()
    assert task["is_overdue"] is True


@freeze_time("2026-10-03T12:00:00")
def test_I4_overdue_boundary_exactly_now_is_not_overdue(client):
    register(client)
    task = create_task(client, due_at="2026-10-03T12:00:00").get_json()
    assert task["is_overdue"] is False


@freeze_time("2026-10-03T12:00:00")
def test_I4_overdue_boundary_one_second_future_is_not_overdue(client):
    register(client)
    task = create_task(client, due_at="2026-10-03T12:00:01").get_json()
    assert task["is_overdue"] is False


def test_I4_task_with_no_due_date_is_never_overdue(client):
    register(client)
    task = create_task(client, due_at=None).get_json()
    assert task["is_overdue"] is False


@freeze_time("2026-10-03T12:00:00")
def test_I4_done_task_with_past_due_date_is_not_overdue(client):
    register(client)
    task = create_task(client, due_at="2020-01-01T00:00:00").get_json()
    client.post(f"/api/tasks/{task['id']}/complete")
    fetched = client.get(f"/api/tasks/{task['id']}").get_json()
    assert fetched["is_overdue"] is False


# --- I5: every write creates exactly one activity row per action (one per
# changed field for updates); an unchanged-field PATCH logs nothing ---


def test_I5_update_logs_one_row_per_changed_field(client):
    register(client)
    task = create_task(client).get_json()

    client.patch(f"/api/tasks/{task['id']}", json={"title": "New title", "tag": "work"})

    activity = client.get("/api/activity").get_json()
    updated_fields = sorted(a["field"] for a in activity if a["action"] == "updated")
    assert updated_fields == ["tag", "title"]


def test_I5_patch_with_unchanged_values_logs_nothing(client):
    register(client)
    task = create_task(client).get_json()

    client.patch(f"/api/tasks/{task['id']}", json={"title": task["title"], "tag": task["tag"]})

    activity = client.get("/api/activity").get_json()
    assert all(a["action"] != "updated" for a in activity)


def test_I5_double_complete_does_not_duplicate_activity(client):
    register(client)
    task = create_task(client).get_json()

    client.post(f"/api/tasks/{task['id']}/complete")
    client.post(f"/api/tasks/{task['id']}/complete")

    activity = client.get("/api/activity").get_json()
    assert [a["action"] for a in activity].count("completed") == 1


# --- I6: completed_at is set iff status == done ---


def test_I6_complete_then_reopen_sets_and_clears_completed_at(client):
    register(client)
    task = create_task(client).get_json()
    assert task["completed_at"] is None

    completed = client.post(f"/api/tasks/{task['id']}/complete").get_json()
    assert completed["status"] == "done"
    assert completed["completed_at"] is not None

    reopened = client.post(f"/api/tasks/{task['id']}/reopen").get_json()
    assert reopened["status"] == "pending"
    assert reopened["completed_at"] is None


# --- Listing: pending-by-due-date-ascending-nulls-last, then done ---


def test_list_orders_pending_by_due_date_then_done_last(client):
    register(client)
    no_due = create_task(client, title="No due date").get_json()
    later = create_task(client, title="Later", due_at="2030-06-01T00:00:00").get_json()
    sooner = create_task(client, title="Sooner", due_at="2030-01-01T00:00:00").get_json()
    done = create_task(client, title="Already done").get_json()
    client.post(f"/api/tasks/{done['id']}/complete")

    titles = [t["title"] for t in client.get("/api/tasks").get_json()]
    assert titles == ["Sooner", "Later", "No due date", "Already done"]
    assert {sooner["id"], later["id"], no_due["id"], done["id"]}  # all referenced


def test_list_filters_by_status_tag_and_search(client):
    register(client)
    create_task(client, title="Write report", tag="work")
    create_task(client, title="Study DBMS", tag="study")
    done = create_task(client, title="Buy groceries", tag="personal").get_json()
    client.post(f"/api/tasks/{done['id']}/complete")

    pending = client.get("/api/tasks?status=pending").get_json()
    assert len(pending) == 2

    work_only = client.get("/api/tasks?tag=work").get_json()
    assert [t["title"] for t in work_only] == ["Write report"]

    searched = client.get("/api/tasks?q=dbms").get_json()
    assert [t["title"] for t in searched] == ["Study DBMS"]
