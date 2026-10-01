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
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        conn.close()
        assert {
            "schema_migrations",
            "users",
            "tasks",
            "activity_log",
            "reminders_sent",
        } <= tables


def test_run_migrations_is_idempotent():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = str(Path(tmp_dir) / "test.db")
        run_migrations(db_path)
        second_run = run_migrations(db_path)
        assert second_run == []
