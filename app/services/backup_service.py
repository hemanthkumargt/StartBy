"""Consistent, compressed snapshot of the SQLite database.

Copying the .db file while the app is writing can capture a torn page, so
the snapshot goes through SQLite's online backup API (which takes a
consistent point-in-time copy even with concurrent writers), then gzip."""

import gzip
import sqlite3
import tempfile
from pathlib import Path

MAX_BACKUP_BYTES = 32 * 1024 * 1024


def snapshot_gzip(db_path: str) -> bytes:
    source = sqlite3.connect(db_path)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            copy_path = Path(tmp) / "snapshot.db"
            dest = sqlite3.connect(copy_path)
            try:
                source.backup(dest)
                # Google refresh tokens grant long-lived calendar access; they
                # must never leave the VM inside a backup. After a restore,
                # users just reconnect Calendar.
                dest.execute("UPDATE calendar_links SET refresh_token = ''")
                dest.commit()
            finally:
                dest.close()
            raw = copy_path.read_bytes()
    finally:
        source.close()
    if len(raw) > MAX_BACKUP_BYTES:
        raise ValueError("database is larger than the simple-upload backup limit")
    return gzip.compress(raw, compresslevel=6)
