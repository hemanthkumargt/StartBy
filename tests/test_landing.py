"""The public landing page: reachable signed out, bounces signed-in users."""

from tests.conftest import register


def test_landing_is_public_and_links_to_signup(client):
    res = client.get("/welcome")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert 'href="/register"' in html and 'href="/login"' in html
    assert "css/landing.css" in html and "js/landing.js" in html


def test_landing_assets_are_served(client):
    assert client.get("/static/css/landing.css").status_code == 200
    assert client.get("/static/js/landing.js").status_code == 200


def test_landing_redirects_signed_in_users_to_dashboard(client):
    register(client)
    res = client.get("/welcome")
    assert res.status_code == 302 and res.location.endswith("/")


def test_signed_out_root_redirects_to_landing(client):
    res = client.get("/")
    assert res.status_code == 302 and "/welcome" in res.location
