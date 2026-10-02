import pytest

from app.db import get_db
from app.repositories import task_repo, user_repo


def test_update_fields_rejects_a_disallowed_column(app):
    """Regression guard: update_fields() builds its SQL SET clause by
    interpolating dict keys directly (column names can't be parameterised),
    so it must refuse anything outside its own whitelist itself rather than
    trusting the caller to have already filtered — defense in depth against
    a future caller that forwards an unfiltered dict."""
    with app.app_context():
        conn = get_db()
        user = user_repo.create(
            conn,
            name="Ada",
            email="ada@example.com",
            password_hash="hash",
            timezone="UTC",
            created_at="2026-01-01T00:00:00",
        )
        row = task_repo.create(
            conn,
            user_id=user["id"],
            title="Test task",
            notes=None,
            tag="work",
            due_at=None,
            created_at="2026-01-01T00:00:00",
        )
        with pytest.raises(ValueError):
            task_repo.update_fields(
                conn,
                row["id"],
                {"deleted_at": "2026-01-01T00:00:00"},
                updated_at="2026-01-01T00:00:00",
            )
