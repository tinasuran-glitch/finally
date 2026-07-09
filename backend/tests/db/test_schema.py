"""Tests for schema creation and default seeding."""

from app.db import connection
from app.db.schema import DEFAULT_WATCHLIST


class TestSchema:
    """Schema creation and seed data."""

    def test_tables_created(self, fresh_db):
        conn = connection.get_connection()
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
        names = {row["name"] for row in rows}
        conn.close()
        expected = {
            "users_profile", "watchlist", "positions",
            "trades", "portfolio_snapshots", "chat_messages",
        }
        assert expected <= names

    def test_default_profile_seeded(self, fresh_db):
        conn = connection.get_connection()
        row = conn.execute(
            "SELECT * FROM users_profile WHERE id = 'default'"
        ).fetchone()
        conn.close()
        assert row["cash_balance"] == 10000.0

    def test_default_watchlist_seeded(self, fresh_db):
        conn = connection.get_connection()
        rows = conn.execute("SELECT ticker FROM watchlist").fetchall()
        conn.close()
        assert {row["ticker"] for row in rows} == set(DEFAULT_WATCHLIST)

    def test_init_is_idempotent(self, fresh_db):
        """A second connection must not duplicate seed rows."""
        connection.get_connection().close()
        connection._initialized.clear()  # force re-init on next connection
        conn = connection.get_connection()
        count = conn.execute("SELECT COUNT(*) AS c FROM watchlist").fetchone()["c"]
        conn.close()
        assert count == len(DEFAULT_WATCHLIST)

    def test_db_path_env_override(self, fresh_db):
        assert connection.db_path() == fresh_db
