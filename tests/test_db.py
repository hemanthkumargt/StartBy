import sqlite3
import tempfile
from pathlib import Path

from app.db import run_migrations


def test_run_migrations_creates_all_tables():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = str(Path(tmp_dir) / "test.db")

        applied = run_migrations(db_path)
        assert applied == ["001_init"]

        conn = sqlite3.connect(db_path)
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        conn.close()
        assert {
            "schema_migrations",
            "users",
            "tasks",
            "activity_log",
            "reminders_sent",
        } <= tables


def test_users_created_at_uses_app_timeutil_format():
    """Regression guard: created_at must come from app.timeutil (T-separated),
    not SQLite's own space-separated datetime('now') column default."""
    import re

    from app.services.auth_service import register as register_user

    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = str(Path(tmp_dir) / "test.db")
        run_migrations(db_path)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        user = register_user(
            conn, name="Ada", email="ada@example.com", password="password123", timezone="UTC"
        )
        row = conn.execute("SELECT created_at FROM users WHERE id = ?", (user.id,)).fetchone()
        conn.close()
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$", row["created_at"])


def test_run_migrations_is_idempotent():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = str(Path(tmp_dir) / "test.db")
        run_migrations(db_path)
        second_run = run_migrations(db_path)
        assert second_run == []
