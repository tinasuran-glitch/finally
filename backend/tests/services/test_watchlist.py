"""Tests for the watchlist service."""

import pytest

from app import state
from app.db import repository as repo
from app.services import watchlist as svc


class FakeSource:
    """Records add/remove calls without a real market data backend."""

    def __init__(self):
        self.added = []
        self.removed = []

    async def add_ticker(self, ticker):
        self.added.append(ticker)

    async def remove_ticker(self, ticker):
        self.removed.append(ticker)


@pytest.fixture
def source(monkeypatch):
    s = FakeSource()
    monkeypatch.setattr(state, "market_source", s)
    return s


def test_get_watchlist_with_prices(fresh_db, cache):
    repo.add_to_watchlist("AAPL")
    entries = svc.get_watchlist()
    aapl = next(e for e in entries if e["ticker"] == "AAPL")
    assert aapl["price"] == 190.0
    assert aapl["direction"] == "flat"


def test_get_watchlist_unknown_price(fresh_db, cache):
    repo.add_to_watchlist("ZZZZ")
    entry = next(e for e in svc.get_watchlist() if e["ticker"] == "ZZZZ")
    assert entry["price"] is None


async def test_add_ticker(fresh_db, cache, source):
    await svc.add_ticker("nvda")
    assert "NVDA" in repo.list_watchlist()
    assert source.added == ["NVDA"]


async def test_remove_ticker(fresh_db, cache, source):
    repo.add_to_watchlist("AAPL")
    await svc.remove_ticker("aapl")
    assert "AAPL" not in repo.list_watchlist()
    assert source.removed == ["AAPL"]
