"""Shared API error shape (PRD architecture rule): {"error": {"code", "message"}}."""

import sqlite3

from flask import Flask, jsonify


class ApiError(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return jsonify({"error": {"code": err.code, "message": err.message}}), err.status

    @app.errorhandler(404)
    def handle_404(_err):
        return jsonify({"error": {"code": "not_found", "message": "Not found"}}), 404

    @app.errorhandler(sqlite3.OperationalError)
    def handle_db_locked(err):
        if "locked" not in str(err).lower() and "busy" not in str(err).lower():
            # Any other database error is a real bug: same generic 500 as always.
            app.logger.exception("database_error")
            return handle_500(err)
        app.logger.error("database_busy error=%s", err)
        return (
            jsonify(
                {
                    "error": {
                        "code": "busy",
                        "message": "The app is busy for a moment — please try again.",
                    }
                }
            ),
            503,
        )

    @app.errorhandler(413)
    def handle_413(_err):
        return (
            jsonify({"error": {"code": "too_large", "message": "Request is too large"}}),
            413,
        )

    @app.errorhandler(500)
    def handle_500(err):
        app.logger.error("unhandled_exception error=%s", err)
        return (
            jsonify({"error": {"code": "internal_error", "message": "Something went wrong"}}),
            500,
        )
