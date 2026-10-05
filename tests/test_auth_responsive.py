"""Regression coverage for fluid authentication layouts."""

from pathlib import Path


AUTH_CSS = (
    Path(__file__).resolve().parent.parent / "app" / "static" / "css" / "auth.css"
).read_text()


def test_auth_layout_removes_global_mobile_min_width():
    assert "@media (max-width: 600px)" in AUTH_CSS
    assert "html,\n  body {\n    min-width: 0" in AUTH_CSS
    assert ".auth-page {\n    width: 100%" in AUTH_CSS
    assert "min-width: 0" in AUTH_CSS


def test_auth_card_and_inputs_are_fluid_on_narrow_devices():
    assert "width: min(100%, 440px)" in AUTH_CSS
    assert "width: 100%;" in AUTH_CSS
    assert "min-width: 0;" in AUTH_CSS
    assert "clamp(1.5rem, 6vw, 2rem)" in AUTH_CSS


def test_auth_layout_accounts_for_landscape_height_and_safe_areas():
    assert "100svh" in AUTH_CSS
    assert "env(safe-area-inset-top)" in AUTH_CSS
    assert "orientation: landscape" in AUTH_CSS


def test_app_supports_short_wide_phone_landscape_viewports():
    app_css = (
        Path(__file__).resolve().parent.parent / "app" / "static" / "css" / "app.css"
    ).read_text()
    query = "@media (min-width: 769px) and (max-width: 1024px) and (max-height: 600px)"
    assert query in app_css
    assert ".app-shell" in app_css
    assert ".mobile-top-bar" in app_css
    assert ".bottom-nav" in app_css


def test_settings_profile_text_can_wrap_on_narrow_screens():
    settings = (
        Path(__file__).resolve().parent.parent
        / "app"
        / "templates"
        / "settings.html"
    ).read_text()
    assert "overflow-wrap: anywhere" in settings
    assert "word-break: break-word" in settings
