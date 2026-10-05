"""Server-rendered page shells (Jinja2). Data and changes go through the
JSON API with fetch — these views never embed task data directly."""

import json
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import Any
from zoneinfo import available_timezones

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    redirect,
    render_template,
    send_from_directory,
    url_for,
)
from flask_login import current_user, login_required

from app.services import calendar_service

bp = Blueprint("pages", __name__)

# Manifest shortcuts that belong to a feature: dropped when its flag is off, so a
# flags-off install installs exactly like v1.0 (I15).
_FEATURE_SHORTCUT_URLS = {"/capture": "FEATURE_SMART_CAPTURE"}


def feature_page(config_key: str) -> Callable:
    """Flag off => the page does not exist, for signed-in AND signed-out visitors
    (404, never a redirect to login that would hint it exists). Apply above
    @login_required."""

    def decorator(view: Callable) -> Callable:
        @wraps(view)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not current_app.config[config_key]:
                abort(404)
            return view(*args, **kwargs)

        return wrapper

    return decorator


_TZ_SKIP_PREFIXES = ("Etc/", "SystemV/", "posix", "right", "US/", "Brazil/", "Canada/", "Chile/")


def _timezone_choices(current: str) -> list[str]:
    """Every real region zone (not the eight a developer happened to type):
    anyone outside those eight was silently moved to Asia/Kolkata by saving."""
    zones = {z for z in available_timezones() if "/" in z and not z.startswith(_TZ_SKIP_PREFIXES)}
    zones |= {"UTC", current}
    return sorted(zones)


@bp.get("/sw.js")
def service_worker():
    """Served from the site root so its scope covers every page (a worker under
    /static/ could only control /static/). no-cache: a new version must be picked up."""
    response = send_from_directory(current_app.static_folder, "sw.js", mimetype="text/javascript")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Service-Worker-Allowed"] = "/"
    return response


@bp.get("/manifest.webmanifest")
def web_manifest():
    """The static manifest minus the shortcuts of features that are switched off."""
    path = Path(current_app.static_folder) / "manifest.webmanifest"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["shortcuts"] = [
        shortcut
        for shortcut in manifest.get("shortcuts", [])
        if current_app.config.get(_FEATURE_SHORTCUT_URLS.get(shortcut["url"], ""), True)
    ]
    return Response(json.dumps(manifest, indent=2), mimetype="application/manifest+json")


@bp.get("/landing")
@bp.get("/welcome")
def landing_page():
    """Public marketing page. Signed-in users go straight to their dashboard."""
    if current_user.is_authenticated:
        return redirect(url_for("pages.home_page"))
    return render_template("landing.html")


@bp.get("/login")
def login_page():
    if current_user.is_authenticated:
        return redirect(url_for("pages.home_page"))
    return render_template("login.html")


@bp.get("/register")
def register_page():
    if current_user.is_authenticated:
        return redirect(url_for("pages.home_page"))
    return render_template("register.html")


@bp.get("/")
def home_page():
    # Signed-out visitors see the public landing page instead of being bounced
    # to /login, so the bare URL is a usable front door.
    if not current_user.is_authenticated:
        return redirect(url_for("pages.landing_page"))
    return render_template(
        "home.html",
        assistant_name=current_user.assistant_name(current_app.config["ASSISTANT_NAME"]),
    )


@bp.get("/tasks")
@login_required
def tasks_page():
    return render_template("tasks.html")


@bp.get("/activity")
@login_required
def activity_page():
    return render_template("activity.html")


@bp.get("/settings")
@login_required
def settings_page():
    return render_template(
        "settings.html",
        calendar_available=calendar_service.is_configured(current_app.config),
        timezones=_timezone_choices(current_user.timezone),
        assistant_default=current_app.config["ASSISTANT_NAME"],
    )


@bp.get("/capture")
@feature_page("FEATURE_SMART_CAPTURE")
@login_required
def capture_page():
    return render_template("capture.html")


@bp.get("/voice")
@feature_page("FEATURE_VOICE")
@login_required
def voice_notes_page():
    return render_template(
        "voice_notes.html",
        assistant_name=current_user.assistant_name(current_app.config["ASSISTANT_NAME"]),
    )


@bp.get("/insights")
@feature_page("FEATURE_INSIGHTS")
@login_required
def insights_page():
    return render_template("insights.html")
