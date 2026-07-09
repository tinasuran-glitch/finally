"""Fixtures for API route tests: temp DB, seeded cache, fake source, TestClient."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import state
from app.api import health, portfolio, watchlist
from app.db import connection
from app.market import PriceCache


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    path = tmp_path / "finally.db"
    monkeypatch.setenv("FINALLY_DB_PATH", str(path))
    connection._initialized.clear()
    yield path
    connection._initialized.clear()


class FakeSource:
    async def add_ticker(self, ticker):
        pass

    async def remove_ticker(self, ticker):
        pass


@pytest.fixture
def client(fresh_db, monkeypatch):
    cache = PriceCache()
    for ticker, price in {"AAPL": 190.0, "GOOGL": 175.0}.items():
        cache.update(ticker, price)
    monkeypatch.setattr(state, "price_cache", cache)
    monkeypatch.setattr(state, "market_source", FakeSource())

    app = FastAPI()
    app.include_router(health.router)
    app.include_router(portfolio.router)
    app.include_router(watchlist.router)
    return TestClient(app)
