from tests.conftest import register


def test_update_dark_mode(client):
    register(client)
    response = client.patch("/api/me", json={"dark_mode": True})
    assert response.status_code == 200
    body = response.get_json()
    assert body["dark_mode"] is True

    # SSR reads it back on the next page load
    page = client.get("/").get_data(as_text=True)
    assert 'data-theme="dark"' in page


def test_update_timezone(client):
    register(client)
    response = client.patch("/api/me", json={"timezone": "UTC"})
    assert response.status_code == 200
    assert response.get_json()["timezone"] == "UTC"


def test_update_rejects_unknown_timezone(client):
    register(client)
    response = client.patch("/api/me", json={"timezone": "Mars/Olympus_Mons"})
    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "validation"


def test_partial_update_leaves_other_field_untouched(client):
    register(client)
    client.patch("/api/me", json={"dark_mode": True})
    response = client.patch("/api/me", json={"timezone": "UTC"})
    body = response.get_json()
    assert body["timezone"] == "UTC"
    assert body["dark_mode"] is True


def test_settings_requires_login(client):
    response = client.patch("/api/me", json={"dark_mode": True})
    assert response.status_code == 302
