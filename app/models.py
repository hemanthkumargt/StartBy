import sqlite3

from flask_login import UserMixin


class User(UserMixin):
    """Thin wrapper around a users row for Flask-Login (no ORM)."""

    def __init__(self, row: sqlite3.Row) -> None:
        self.id = row["id"]
        self.name = row["name"]
        self.email = row["email"]
        self.timezone = row["timezone"]
        self.dark_mode = bool(row["dark_mode"])

    def get_id(self) -> str:
        return str(self.id)
