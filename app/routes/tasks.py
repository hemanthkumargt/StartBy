from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required

from app.db import get_db
from app.errors import ApiError
from app.feature_flags import read_feature_flags
from app.services import activity_service, task_service

bp = Blueprint("tasks", __name__, url_prefix="/api")


def _json_body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("validation", "Request body must be JSON", 422)
    return data


def _flags() -> dict:
    return read_feature_flags(current_app.config)


@bp.get("/tasks")
@login_required
def list_tasks():
    tasks = task_service.list_tasks(
        get_db(),
        user_id=current_user.id,
        status=request.args.get("status"),
        tag=request.args.get("tag"),
        q=request.args.get("q"),
        flags=_flags(),
    )
    return jsonify(tasks), 200


@bp.post("/tasks")
@login_required
def create_task():
    body = _json_body()
    task = task_service.create_task(
        get_db(),
        user_id=current_user.id,
        title=body.get("title", ""),
        notes=body.get("notes"),
        tag=body.get("tag"),
        due_at=body.get("due_at"),
        estimate_hours=body.get("estimate_hours"),
        flags=_flags(),
    )
    return jsonify(task), 201


@bp.get("/tasks/<int:task_id>")
@login_required
def get_task(task_id: int):
    task = task_service.get_task(get_db(), user_id=current_user.id, task_id=task_id, flags=_flags())
    return jsonify(task), 200


@bp.patch("/tasks/<int:task_id>")
@login_required
def update_task(task_id: int):
    body = _json_body()
    task = task_service.update_task(
        get_db(),
        user_id=current_user.id,
        task_id=task_id,
        fields=body,
        flags=_flags(),
    )
    return jsonify(task), 200


@bp.post("/tasks/<int:task_id>/complete")
@login_required
def complete_task(task_id: int):
    task = task_service.complete_task(
        get_db(), user_id=current_user.id, task_id=task_id, flags=_flags()
    )
    return jsonify(task), 200


@bp.post("/tasks/<int:task_id>/reopen")
@login_required
def reopen_task(task_id: int):
    task = task_service.reopen_task(
        get_db(), user_id=current_user.id, task_id=task_id, flags=_flags()
    )
    return jsonify(task), 200


@bp.delete("/tasks/<int:task_id>")
@login_required
def delete_task(task_id: int):
    task_service.delete_task(get_db(), user_id=current_user.id, task_id=task_id)
    return "", 204


@bp.get("/dashboard")
@login_required
def dashboard():
    dashboard_data = task_service.get_dashboard(get_db(), user_id=current_user.id, flags=_flags())
    return jsonify(dashboard_data), 200


@bp.get("/activity")
@login_required
def activity():
    limit = request.args.get("limit", default=50, type=int)
    before = request.args.get("before", type=int)
    entries = activity_service.list_activity(
        get_db(), current_user.id, limit=limit, before_id=before
    )
    return jsonify(entries), 200
