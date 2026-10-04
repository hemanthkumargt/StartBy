"""Business rules for registration and login (routes stay HTTP-only)."""

import re
import sqlite3
from zoneinfo import available_timezones

from werkzeug.security import check_password_hash, generate_password_hash

from app import timeutil
from app.errors import ApiError
from app.models import User
from app.repositories import user_repo
from app.validation import require_str

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LENGTH = 8
# Unbounded fields let one anonymous request put megabytes in the database (and
# push it past the nightly backup's size limit).
MAX_NAME_LENGTH = 100
MAX_EMAIL_LENGTH = 254
MAX_PASSWORD_LENGTH = 128

# Hashed once at import time and used whenever the email doesn't match any
# account, so authenticate() always pays the same hashing cost — without
# this, an unknown email returns faster than a wrong password and response
# timing alone reveals which accounts exist.
_DUMMY_PASSWORD_HASH = generate_password_hash("not-a-real-password-used-only-for-timing-safety")


def pick_timezone(requested: object, default: str) -> str:
    """The browser's own timezone if it sent a valid one, else the default.
    Without this every new account is on Asia/Kolkata whatever their clock says,
    and the times they type and the times they are shown drift apart."""
    if isinstance(requested, str) and requested in available_timezones():
        return requested
    return default


def register(
    conn: sqlite3.Connection, *, name: object, email: object, password: object, timezone: str
) -> User:
    name = require_str(name, "name").strip()
    email = require_str(email, "email").strip().lower()
    password = require_str(password, "password")

    if not name:
        raise ApiError("validation", "Name is required", 422)
    if len(name) > MAX_NAME_LENGTH:
        raise ApiError("validation", f"Name must be at most {MAX_NAME_LENGTH} characters", 422)
    if len(email) > MAX_EMAIL_LENGTH or not EMAIL_RE.match(email):
        raise ApiError("validation", "A valid email is required", 422)
    if len(password) > MAX_PASSWORD_LENGTH:
        raise ApiError(
            "validation", f"Password must be at most {MAX_PASSWORD_LENGTH} characters", 422
        )
    if not password or len(password) < MIN_PASSWORD_LENGTH:
        raise ApiError(
            "validation", f"Password must be at least {MIN_PASSWORD_LENGTH} characters", 422
        )
    if user_repo.find_by_email(conn, email) is not None:
        raise ApiError("email_taken", "An account with that email already exists", 422)

    password_hash = generate_password_hash(password)
    try:
        row = user_repo.create(
            conn,
            name=name,
            email=email,
            password_hash=password_hash,
            timezone=timezone,
            created_at=timeutil.utcnow_iso(),
        )
    except sqlite3.IntegrityError as exc:
        # Two tabs / a double click registering the same email at once: the
        # check above passed for both, the UNIQUE index stops the second.
        raise ApiError("email_taken", "An account with that email already exists", 422) from exc
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


def social_authenticate_or_register(
    conn: sqlite3.Connection,
    *,
    provider: str,
    email: object,
    name: object,
    timezone: str,
) -> User:
    import secrets

    email_str = require_str(email, "email").strip().lower()
    name_str = require_str(name, "name").strip() if name else ""

    if not EMAIL_RE.match(email_str):
        raise ApiError("validation", "A valid email is required", 422)

    if not name_str:
        name_str = email_str.split("@")[0].replace(".", " ").title()

    existing = user_repo.find_by_email(conn, email_str)
    if existing is not None:
        return User(existing)

    random_password = secrets.token_urlsafe(32)
    password_hash = generate_password_hash(random_password)
    row = user_repo.create(
        conn,
        name=name_str,
        email=email_str,
        password_hash=password_hash,
        timezone=timezone,
        created_at=timeutil.utcnow_iso(),
    )
    return User(row)
