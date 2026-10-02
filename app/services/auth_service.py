"""Business rules for registration and login (routes stay HTTP-only)."""

import re
import sqlite3

from werkzeug.security import check_password_hash, generate_password_hash

from app import timeutil
from app.errors import ApiError
from app.models import User
from app.repositories import user_repo
from app.validation import require_str

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LENGTH = 8

# Hashed once at import time and used whenever the email doesn't match any
# account, so authenticate() always pays the same hashing cost — without
# this, an unknown email returns faster than a wrong password and response
# timing alone reveals which accounts exist.
_DUMMY_PASSWORD_HASH = generate_password_hash("not-a-real-password-used-only-for-timing-safety")


def register(
    conn: sqlite3.Connection, *, name: object, email: object, password: object, timezone: str
) -> User:
    name = require_str(name, "name").strip()
    email = require_str(email, "email").strip().lower()
    password = require_str(password, "password")

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


def authenticate(conn: sqlite3.Connection, *, email: object, password: object) -> User:
    email = require_str(email, "email").strip().lower()
    password = require_str(password, "password")
    row = user_repo.find_by_email(conn, email)
    password_hash = row["password_hash"] if row is not None else _DUMMY_PASSWORD_HASH
    password_ok = check_password_hash(password_hash, password)
    if row is None or not password_ok:
        raise ApiError("invalid_credentials", "Incorrect email or password", 401)
    return User(row)
