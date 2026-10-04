"""SQLite connection per request, plus a tiny migration runner.

No ORM (PRD constraint): parameterised SQL only, everywhere.
"""

import sqlite3
from pathlib import Path

from flask import Flask, current_app, g

BUSY_TIMEOUT_SECONDS = 15
MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        db_path = Path(current_app.config["DATABASE_PATH"])
        db_path.parent.mkdir(parents=True, exist_ok=True)
        # Two gunicorn workers, the Calendar sync thread and the nightly backup
        # all write this one file; wait up to 15s for the write lock rather than
        # failing a user's request after SQLite's default 5s.
        conn = sqlite3.connect(str(db_path), timeout=BUSY_TIMEOUT_SECONDS)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        g.db = conn
    return g.db


def close_db(_exception: BaseException | None = None) -> None:
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def _applied_versions(conn: sqlite3.Connection) -> set[str]:
    try:
        rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
        return {row["version"] for row in rows}
    except sqlite3.OperationalError:
        return set()


def run_migrations(db_path: str) -> list[str]:
    """Apply every migrations/*.sql not yet recorded, in filename order.
    Returns the list of versions applied this call (empty if already current).
    """
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        applied = _applied_versions(conn)
        applied_now = []
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            version = path.stem
            if version in applied:
                continue
            script = path.read_text()
            conn.executescript(script)
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)",
                (version,),
            )
            conn.commit()
            applied_now.append(version)
        return applied_now
    finally:
        conn.close()


def init_app(app: Flask) -> None:
    app.teardown_appcontext(close_db)
    with app.app_context():
        run_migrations(app.config["DATABASE_PATH"])
