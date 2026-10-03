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


def test_register_rejects_blank_name(client):
    response = register(client, name="   ")
    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "validation"


def test_register_rejects_duplicate_email(client):
    register(client)
    response = register(client, name="Second Ada")
    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "email_taken"


def test_register_rejects_non_string_name_with_422_not_500(client):
    """Regression guard: (name or "").strip() used to crash with an
    uncaught AttributeError on a truthy non-string JSON value (e.g. a
    number or list) instead of returning a validation error."""
    response = client.post(
        "/api/auth/register",
        json={"name": 123, "email": "ada@example.com", "password": "password123"},
    )
    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "validation"


def test_register_rejects_non_string_password_with_422_not_500(client):
    response = client.post(
        "/api/auth/register",
        json={"name": "Ada", "email": "ada@example.com", "password": 12345678},
    )
    assert response.status_code == 422


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


def test_login_hashes_password_even_for_an_unknown_email(client, monkeypatch):
    """Regression guard: authenticate() used to short-circuit on `row is
    None`, skipping check_password_hash entirely for an unknown email.
    Response-timing alone would then reveal whether an account exists. It
    must now run the (deliberately slow) hash check unconditionally."""
    calls = []
    import app.services.auth_service as auth_service_module

    original = auth_service_module.check_password_hash

    def spy(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(auth_service_module, "check_password_hash", spy)

    login(client, email="nobody@example.com")

    assert len(calls) == 1


def test_logout_requires_login(client):
    response = client.post("/api/auth/logout")
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "unauthorized"


def test_logout_ends_session(client):
    register(client)
    response = client.post("/api/auth/logout")
    assert response.status_code == 204

    home = client.get("/")
    assert home.status_code == 302


def test_home_page_requires_login(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_social_login_registers_new_user(client):
    res = client.post(
        "/api/auth/social",
        json={"provider": "google", "email": "judge@gmail.com", "name": "Judge Demo"},
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["email"] == "judge@gmail.com"
    assert data["name"] == "Judge Demo"

    # Verifies session is authenticated
    home = client.get("/")
    assert home.status_code == 200


def test_social_login_authenticates_existing_user(client):
    client.post(
        "/api/auth/social",
        json={"provider": "google", "email": "alex@startby.demo", "name": "Alex Demo"},
    )
    client.post("/api/auth/logout")

    res = client.post(
        "/api/auth/social",
        json={"provider": "google", "email": "alex@startby.demo", "name": "Alex Demo"},
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["email"] == "alex@startby.demo"
