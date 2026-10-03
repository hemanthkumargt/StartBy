from tests.conftest import register


def test_dashboard_due_next_is_limited_to_five_soonest(client):
    register(client)
    for day in range(1, 8):  # 7 pending tasks with due dates
        client.post(
            "/api/tasks",
            json={"title": f"Task {day}", "due_at": f"2030-01-{day:02d}T00:00:00"},
        )
    client.post("/api/tasks", json={"title": "No due date"})

    dashboard = client.get("/api/dashboard").get_json()
    due_next = dashboard["due_next"]
    assert len(due_next) == 5
    assert [t["title"] for t in due_next] == [f"Task {d}" for d in range(1, 6)]


def test_dashboard_on_empty_account_is_all_zero(client):
    # Subset check, not exact-equality: exact-equality would silently depend
    # on this fixture's FEATURE_ESTIMATES default (do_this_now only appears
    # when it's on) rather than actually asserting anything about that flag.
    register(client)
    dashboard = client.get("/api/dashboard").get_json()
    assert dashboard["total"] == 0
    assert dashboard["completed"] == 0
    assert dashboard["pending"] == 0
    assert dashboard["overdue"] == 0
    assert dashboard["due_next"] == []
