"""Tests for repository CRUD functions."""

from app.db import repository as repo


class TestProfile:
    def test_get_default_profile(self, fresh_db):
        profile = repo.get_profile()
        assert profile["id"] == "default"
        assert profile["cash_balance"] == 10000.0

    def test_update_cash_balance(self, fresh_db):
        repo.update_cash_balance(8500.0)
        assert repo.get_profile()["cash_balance"] == 8500.0


class TestWatchlist:
    def test_default_list(self, fresh_db):
        assert "AAPL" in repo.list_watchlist()
        assert len(repo.list_watchlist()) == 10

    def test_add(self, fresh_db):
        repo.add_to_watchlist("PYPL")
        assert "PYPL" in repo.list_watchlist()

    def test_add_duplicate_is_noop(self, fresh_db):
        before = len(repo.list_watchlist())
        repo.add_to_watchlist("AAPL")
        assert len(repo.list_watchlist()) == before

    def test_remove(self, fresh_db):
        repo.remove_from_watchlist("AAPL")
        assert "AAPL" not in repo.list_watchlist()

    def test_remove_nonexistent_is_noop(self, fresh_db):
        before = len(repo.list_watchlist())
        repo.remove_from_watchlist("ZZZZ")
        assert len(repo.list_watchlist()) == before


class TestPositions:
    def test_empty_by_default(self, fresh_db):
        assert repo.list_positions() == []
        assert repo.get_position("AAPL") is None

    def test_upsert_creates(self, fresh_db):
        row = repo.upsert_position("AAPL", 10, 190.0)
        assert row["quantity"] == 10
        assert row["avg_cost"] == 190.0
        assert repo.get_position("AAPL")["quantity"] == 10

    def test_upsert_twice_updates_in_place(self, fresh_db):
        repo.upsert_position("AAPL", 10, 190.0)
        repo.upsert_position("AAPL", 15, 195.0)
        assert len(repo.list_positions()) == 1
        pos = repo.get_position("AAPL")
        assert pos["quantity"] == 15
        assert pos["avg_cost"] == 195.0

    def test_delete(self, fresh_db):
        repo.upsert_position("AAPL", 10, 190.0)
        repo.delete_position("AAPL")
        assert repo.get_position("AAPL") is None

    def test_delete_nonexistent_is_noop(self, fresh_db):
        repo.delete_position("AAPL")
        assert repo.get_position("AAPL") is None


class TestTrades:
    def test_record_and_list(self, fresh_db):
        trade = repo.record_trade("AAPL", "buy", 10, 190.0)
        assert trade["side"] == "buy"
        assert trade["quantity"] == 10
        trades = repo.list_trades()
        assert len(trades) == 1
        assert trades[0]["id"] == trade["id"]

    def test_list_most_recent_first(self, fresh_db):
        repo.record_trade("AAPL", "buy", 1, 100.0)
        repo.record_trade("GOOGL", "buy", 2, 200.0)
        trades = repo.list_trades()
        assert trades[0]["ticker"] == "GOOGL"

    def test_list_respects_limit(self, fresh_db):
        for _ in range(5):
            repo.record_trade("AAPL", "buy", 1, 100.0)
        assert len(repo.list_trades(limit=3)) == 3


class TestSnapshots:
    def test_record_and_list(self, fresh_db):
        repo.record_snapshot(10000.0)
        repo.record_snapshot(10500.0)
        snaps = repo.list_snapshots()
        assert len(snaps) == 2
        assert snaps[0]["total_value"] == 10000.0  # chronological

    def test_empty_by_default(self, fresh_db):
        assert repo.list_snapshots() == []


class TestChatMessages:
    def test_add_user_message_no_actions(self, fresh_db):
        msg = repo.add_chat_message("user", "hello")
        assert msg["role"] == "user"
        assert msg["actions"] is None

    def test_add_assistant_message_with_actions(self, fresh_db):
        actions = {"trades": [{"ticker": "AAPL", "side": "buy", "quantity": 10}]}
        msg = repo.add_chat_message("assistant", "Bought.", actions=actions)
        assert msg["actions"] == actions

    def test_list_chronological_order(self, fresh_db):
        repo.add_chat_message("user", "first")
        repo.add_chat_message("assistant", "second")
        msgs = repo.list_chat_messages()
        assert [m["content"] for m in msgs] == ["first", "second"]

    def test_list_respects_limit(self, fresh_db):
        for i in range(5):
            repo.add_chat_message("user", f"msg {i}")
        assert len(repo.list_chat_messages(limit=2)) == 2

    def test_empty_by_default(self, fresh_db):
        assert repo.list_chat_messages() == []
