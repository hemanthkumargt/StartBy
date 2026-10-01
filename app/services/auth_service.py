"""Business rules for registration and login (routes stay HTTP-only)."""

import re
import sqlite3

from werkzeug.security import check_password_hash, generate_password_hash

from app import timeutil
from app.errors import ApiError
from app.models import User
from app.repositories import user_repo

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LENGTH = 8


def register(
    conn: sqlite3.Connection, *, name: str, email: str, password: str, timezone: str
) -> User:
    name = (name or "").strip()
    email = (email or "").strip().lower()

    if not name:
        raise ApiError("validation", "Name is required", 422)
    if not EMAIL_RE.match(email):
        raise ApiError("validation", "A valid email is required", 422)
    if not password or len(password) < MIN_PASSWORD_LENGTH:
        raise ApiError(
            "validation", f"Password must be at least {MIN_PASSWORD_LENGTH} characters", 422
        )
    if user_repo.find_by_email(conn, email) is not None:
        raise ApiError("email_taken", "An account with that email already exists", 422)

    password_hash = generate_password_hash(password)
    row = user_repo.create(
        conn,
        name=name,
        email=email,
        password_hash=password_hash,
        timezone=timezone,
        created_at=timeutil.utcnow_iso(),
    )
    return User(row)


def authenticate(conn: sqlite3.Connection, *, email: str, password: str) -> User:
    email = (email or "").strip().lower()
    row = user_repo.find_by_email(conn, email)
    if row is None or not check_password_hash(row["password_hash"], password or ""):
        raise ApiError("invalid_credentials", "Incorrect email or password", 401)
    return User(row)
