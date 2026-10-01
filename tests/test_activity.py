from tests.conftest import register


def test_activity_is_newest_first(client):
    register(client)
    client.post("/api/tasks", json={"title": "First"})
    client.post("/api/tasks", json={"title": "Second"})

    activity = client.get("/api/activity").get_json()
    # newest (Second's "created" row) comes first
    assert activity[0]["new_value"] is None  # created rows carry no field/value
    ids = [a["id"] for a in activity]
    assert ids == sorted(ids, reverse=True)


def test_activity_respects_limit_and_before_cursor(client):
    register(client)
    for i in range(5):
        client.post("/api/tasks", json={"title": f"Task {i}"})

    first_page = client.get("/api/activity?limit=2").get_json()
    assert len(first_page) == 2

    cursor = first_page[-1]["id"]
    second_page = client.get(f"/api/activity?limit=2&before={cursor}").get_json()
    assert len(second_page) == 2
    assert all(entry["id"] < cursor for entry in second_page)
