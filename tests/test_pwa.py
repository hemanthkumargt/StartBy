"""The app is installable on Android and iPhone: manifest, icons, worker, tags."""

import json
import struct
from pathlib import Path

import pytest

from tests.conftest import register

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"


def test_manifest_is_valid_and_points_at_real_icons(client):
    res = client.get("/manifest.webmanifest")
    assert res.status_code == 200
    assert res.mimetype == "application/manifest+json"
    manifest = json.loads(res.data)
    assert manifest["display"] == "standalone" and manifest["start_url"].startswith("/")
    sizes = {i["sizes"]: i for i in manifest["icons"]}
    assert {"192x192", "512x512"} <= set(sizes)
    assert any(i.get("purpose") == "maskable" for i in manifest["icons"])
    for icon in manifest["icons"]:
        assert client.get(icon["src"]).status_code == 200, icon["src"]


@pytest.mark.parametrize(
    "name,size",
    [
        ("icon-192.png", 192),
        ("icon-512.png", 512),
        ("icon-maskable-512.png", 512),
        ("apple-touch-icon.png", 180),
    ],
)
def test_icons_are_pngs_of_the_declared_size(name, size):
    data = (STATIC / "icons" / name).read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", data[16:24])
    assert (width, height) == (size, size)


def test_service_worker_is_served_from_the_root_scope_and_not_cached(client):
    res = client.get("/sw.js")
    assert res.status_code == 200
    assert res.mimetype in ("text/javascript", "application/javascript")
    assert res.headers["Service-Worker-Allowed"] == "/"
    assert "no-cache" in res.headers["Cache-Control"]


def test_service_worker_never_caches_pages_or_the_api():
    """Private task data must not be readable from a cache on a shared device."""
    source = (STATIC / "sw.js").read_text()
    assert 'req.method !== "GET"' in source
    assert 'req.mode === "navigate"' in source and "caches.match(OFFLINE_URL)" in source
    # the only thing put into the cache is under /static/
    assert source.count("c.put(") == 1 and 'url.pathname.startsWith("/static/")' in source
    assert "/api/" not in source.split("Everything else")[0].replace("the JSON API", "")


def test_offline_page_exists_and_is_self_contained():
    html = (STATIC / "offline.html").read_text()
    assert "offline" in html.lower() and "<link" not in html and "src=" not in html


def test_pages_carry_the_mobile_app_tags(client):
    register(client)
    html = client.get("/").get_data(as_text=True)
    for needle in (
        "viewport-fit=cover",
        'rel="manifest"',
        'rel="apple-touch-icon"',
        'name="theme-color"',
        "apple-mobile-web-app-capable",
        "serviceWorker.register",
    ):
        assert needle in html, needle


def test_phone_tab_bar_marks_the_current_page_and_follows_feature_flags(app, client):
    register(client)
    html = client.get("/tasks").get_data(as_text=True)
    assert 'class="bottom-nav"' in html
    assert 'href="/tasks" class="bottom-nav__item is-active" aria-current="page"' in html
    assert 'href="/capture" class="bottom-nav__item' not in html
    app.config["FEATURE_SMART_CAPTURE"] = True
    app.config["FEATURE_INSIGHTS"] = True
    html = client.get("/").get_data(as_text=True)
    assert 'href="/capture" class="bottom-nav__item' in html
    assert 'href="/insights" class="bottom-nav__item' in html


def test_no_tab_bar_for_signed_out_visitors(client):
    assert 'class="bottom-nav"' not in client.get("/login").get_data(as_text=True)
