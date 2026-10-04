import sqlite3


def get_link(conn: sqlite3.Connection, user_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT user_id, refresh_token, connected_at FROM calendar_links WHERE user_id = ?",
        (user_id,),
    ).fetchone()


def upsert_link(conn: sqlite3.Connection, user_id: int, refresh_token: str) -> None:
    conn.execute(
        """
        INSERT INTO calendar_links (user_id, refresh_token) VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET refresh_token = excluded.refresh_token,
                                           connected_at = datetime('now')
        """,
        (user_id, refresh_token),
    )
    conn.commit()


def delete_link(conn: sqlite3.Connection, user_id: int) -> None:
    """Disconnecting also forgets the event mapping: the events themselves
    stay in the user's calendar (we may no longer hold a valid token), but
    nothing here should try to patch them afterwards."""
    conn.execute("DELETE FROM calendar_events WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM calendar_links WHERE user_id = ?", (user_id,))
    conn.commit()


def get_event(conn: sqlite3.Connection, task_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT task_id, user_id, event_id FROM calendar_events WHERE task_id = ?", (task_id,)
    ).fetchone()


def upsert_event(conn: sqlite3.Connection, task_id: int, user_id: int, event_id: str) -> None:
    conn.execute(
        """
        INSERT INTO calendar_events (task_id, user_id, event_id) VALUES (?, ?, ?)
        ON CONFLICT(task_id) DO UPDATE SET event_id = excluded.event_id
        """,
        (task_id, user_id, event_id),
    )
    conn.commit()


def delete_event(conn: sqlite3.Connection, task_id: int) -> None:
    conn.execute("DELETE FROM calendar_events WHERE task_id = ?", (task_id,))
    conn.commit()


def list_event_ids(conn: sqlite3.Connection, user_id: int) -> list[str]:
    rows = conn.execute(
        "SELECT event_id FROM calendar_events WHERE user_id = ?", (user_id,)
    ).fetchall()
    return [row["event_id"] for row in rows]
