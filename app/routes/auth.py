from flask import Blueprint, current_app, jsonify, request, session
from flask_login import login_required, login_user, logout_user

from app.db import get_db
from app.errors import ApiError
from app.ratelimit import key_for
from app.services import auth_service

bp = Blueprint("auth", __name__, url_prefix="/api/auth")

_TOO_MANY = "Too many attempts — wait a few minutes and try again"


def _limiters() -> dict:
    return current_app.extensions["auth_limiters"]


def _client() -> str:
    return request.remote_addr or "unknown"


def _json_body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("validation", "Request body must be JSON", 422)
    return data


@bp.post("/register")
def register():
    if not _limiters()["register"].allow(_client()):
        raise ApiError("rate_limited", "Too many sign-ups from this network — wait a minute", 429)
    body = _json_body()
    user = auth_service.register(
        get_db(),
        name=body.get("name", ""),
        email=body.get("email", ""),
        password=body.get("password", ""),
        timezone=auth_service.pick_timezone(
            body.get("timezone"), current_app.config["DEFAULT_TIMEZONE"]
        ),
    )
    login_user(user)
    return jsonify({"id": user.id, "name": user.name, "email": user.email}), 201


@bp.post("/login")
def login():
    body = _json_body()
    limiters = _limiters()
    email = body.get("email")
    pair = key_for(_client(), email.strip().lower() if isinstance(email, str) else "")
    if limiters["login_ip"].blocked(_client()) or limiters["login_pair"].blocked(pair):
        raise ApiError("rate_limited", _TOO_MANY, 429)
    try:
        user = auth_service.authenticate(
            get_db(), email=body.get("email", ""), password=body.get("password", "")
        )
    except ApiError as exc:
        if exc.code == "invalid_credentials":
            limiters["login_pair"].hit(pair)
            limiters["login_ip"].hit(_client())
        raise
    login_user(user, remember=bool(body.get("remember")))
    return jsonify({"id": user.id, "name": user.name, "email": user.email}), 200


@bp.post("/social")
def social_login():
    if not current_app.config["ALLOW_DEMO_SOCIAL_LOGIN"]:
        raise ApiError("not_found", "Not found", 404)
    body = _json_body()
    user = auth_service.social_authenticate_or_register(
        get_db(),
        provider=body.get("provider", "google"),
        email=body.get("email", ""),
        name=body.get("name", ""),
        timezone=current_app.config["DEFAULT_TIMEZONE"],
    )
    login_user(user)
    return jsonify({"id": user.id, "name": user.name, "email": user.email}), 200


@bp.post("/logout")
@login_required
def logout():
    logout_user()
    # A half-finished Calendar OAuth attempt must not survive into the next
    # person who signs in on this browser.
    session.pop("calendar_oauth_state", None)
    return "", 204
