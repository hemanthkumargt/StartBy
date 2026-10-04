import sqlite3


def create(conn: sqlite3.Connection, user_id: int, title: str, transcript: str) -> int:
    cur = conn.execute(
        "INSERT INTO voice_notes (user_id, title, transcript) VALUES (?, ?, ?)",
        (user_id, title, transcript),
    )
    conn.commit()
    return int(cur.lastrowid)


def list_for_user(conn: sqlite3.Connection, user_id: int, limit: int) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT id, user_id, title, transcript, created_at FROM voice_notes
        WHERE user_id = ? ORDER BY created_at DESC, id DESC LIMIT ?
        """,
        (user_id, limit),
    ).fetchall()


def get(conn: sqlite3.Connection, note_id: int, user_id: int) -> sqlite3.Row | None:
    """Scoped by user in the query itself: someone else's note is simply absent (I1)."""
    return conn.execute(
        """
        SELECT id, user_id, title, transcript, created_at FROM voice_notes
        WHERE id = ? AND user_id = ?
        """,
        (note_id, user_id),
    ).fetchone()


def count_for_user(conn: sqlite3.Connection, user_id: int) -> int:
    return int(
        conn.execute("SELECT COUNT(*) FROM voice_notes WHERE user_id = ?", (user_id,)).fetchone()[0]
    )


def delete(conn: sqlite3.Connection, note_id: int, user_id: int) -> bool:
    cur = conn.execute("DELETE FROM voice_notes WHERE id = ? AND user_id = ?", (note_id, user_id))
    conn.commit()
    return cur.rowcount > 0
