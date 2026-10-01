"""Server-rendered page shells (Jinja2). Data and changes go through the
JSON API with fetch — these views never embed task data directly."""

from flask import Blueprint, redirect, render_template, url_for
from flask_login import current_user, login_required

bp = Blueprint("pages", __name__)


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
@login_required
def home_page():
    return render_template("home.html")


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
    return render_template("settings.html")
