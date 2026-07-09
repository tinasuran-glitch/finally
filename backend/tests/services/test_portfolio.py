"""Tests for portfolio valuation and trade execution."""

import pytest

from app.db import repository as repo
from app.services import portfolio as svc


def test_empty_portfolio(fresh_db, cache):
    p = svc.get_portfolio()
    assert p["cash_balance"] == 10000.0
    assert p["positions"] == []
    assert p["total_value"] == 10000.0


def test_buy_updates_cash_and_position(fresh_db, cache):
    trade = svc.execute_trade("AAPL", "buy", 10)
    assert trade["ticker"] == "AAPL"
    assert trade["side"] == "buy"
    assert trade["price"] == 190.0

    p = svc.get_portfolio()
    assert p["cash_balance"] == 10000.0 - 1900.0
    assert len(p["positions"]) == 1
    pos = p["positions"][0]
    assert pos["ticker"] == "AAPL"
    assert pos["quantity"] == 10
    assert pos["avg_cost"] == 190.0
    assert p["total_value"] == pytest.approx(10000.0)


def test_buy_weighted_average_cost(fresh_db, cache):
    svc.execute_trade("AAPL", "buy", 10)
    cache.update("AAPL", 210.0)
    svc.execute_trade("AAPL", "buy", 10)
    pos = repo.get_position("AAPL")
    assert pos["quantity"] == 20
    assert pos["avg_cost"] == pytest.approx(200.0)


def test_valuation_with_gain(fresh_db, cache):
    svc.execute_trade("AAPL", "buy", 10)
    cache.update("AAPL", 200.0)
    pos = svc.get_portfolio()["positions"][0]
    assert pos["current_price"] == 200.0
    assert pos["unrealized_pnl"] == pytest.approx(100.0)
    assert pos["pnl_percent"] == pytest.approx(5.26, abs=0.01)


def test_sell_reduces_position(fresh_db, cache):
    svc.execute_trade("AAPL", "buy", 10)
    svc.execute_trade("AAPL", "sell", 4)
    pos = repo.get_position("AAPL")
    assert pos["quantity"] == 6
    p = svc.get_portfolio()
    assert p["cash_balance"] == pytest.approx(10000.0 - 1900.0 + 760.0)


def test_sell_all_deletes_position(fresh_db, cache):
    svc.execute_trade("AAPL", "buy", 10)
    svc.execute_trade("AAPL", "sell", 10)
    assert repo.get_position("AAPL") is None
    assert svc.get_portfolio()["cash_balance"] == pytest.approx(10000.0)


def test_buy_insufficient_cash(fresh_db, cache):
    with pytest.raises(ValueError, match="Insufficient cash"):
        svc.execute_trade("AAPL", "buy", 1000)


def test_sell_insufficient_shares(fresh_db, cache):
    svc.execute_trade("AAPL", "buy", 5)
    with pytest.raises(ValueError, match="Insufficient shares"):
        svc.execute_trade("AAPL", "sell", 10)


def test_invalid_ticker(fresh_db, cache):
    with pytest.raises(ValueError, match="No market price"):
        svc.execute_trade("ZZZZ", "buy", 1)


def test_non_positive_quantity(fresh_db, cache):
    with pytest.raises(ValueError, match="greater than zero"):
        svc.execute_trade("AAPL", "buy", 0)


def test_trade_records_snapshot(fresh_db, cache):
    svc.execute_trade("AAPL", "buy", 10)
    snapshots = svc.get_history()
    assert len(snapshots) == 1
    assert snapshots[0]["total_value"] == pytest.approx(10000.0)


def test_ticker_case_insensitive(fresh_db, cache):
    svc.execute_trade("aapl", "buy", 1)
    assert repo.get_position("AAPL")["quantity"] == 1
