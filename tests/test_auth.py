from tests.conftest import login, register


def test_register_creates_account_and_logs_in(client):
    response = register(client)
    assert response.status_code == 201
    body = response.get_json()
    assert body["email"] == "ada@example.com"

    # session is active immediately after register
    home = client.get("/")
    assert home.status_code == 200


def test_register_rejects_short_password(client):
    response = register(client, password="short")
    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "validation"


def test_register_rejects_invalid_email(client):
    response = register(client, email="not-an-email")
    assert response.status_code == 422


def test_register_rejects_duplicate_email(client):
    register(client)
    response = register(client, name="Second Ada")
    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "email_taken"


def test_login_with_correct_credentials(client):
    register(client)
    client.post("/api/auth/logout")
    response = login(client)
    assert response.status_code == 200


def test_login_rejects_wrong_password(client):
    register(client)
    client.post("/api/auth/logout")
    response = login(client, password="wrong-password")
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "invalid_credentials"


def test_login_rejects_unknown_email(client):
    response = login(client, email="nobody@example.com")
    assert response.status_code == 401


def test_logout_requires_login(client):
    response = client.post("/api/auth/logout")
    assert response.status_code in (302, 401)


def test_logout_ends_session(client):
    register(client)
    response = client.post("/api/auth/logout")
    assert response.status_code == 204

    home = client.get("/")
    assert home.status_code in (302, 401)


def test_home_page_requires_login(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
