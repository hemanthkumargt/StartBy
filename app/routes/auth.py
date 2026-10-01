from flask import Blueprint, current_app, jsonify, request
from flask_login import login_required, login_user, logout_user

from app.db import get_db
from app.errors import ApiError
from app.services import auth_service

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def _json_body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("validation", "Request body must be JSON", 422)
    return data


@bp.post("/register")
def register():
    body = _json_body()
    user = auth_service.register(
        get_db(),
        name=body.get("name", ""),
        email=body.get("email", ""),
        password=body.get("password", ""),
        timezone=current_app.config["DEFAULT_TIMEZONE"],
    )
    login_user(user)
    return jsonify({"id": user.id, "name": user.name, "email": user.email}), 201


@bp.post("/login")
def login():
    body = _json_body()
    user = auth_service.authenticate(
        get_db(), email=body.get("email", ""), password=body.get("password", "")
    )
    login_user(user)
    return jsonify({"id": user.id, "name": user.name, "email": user.email}), 200


@bp.post("/logout")
@login_required
def logout():
    logout_user()
    return "", 204
