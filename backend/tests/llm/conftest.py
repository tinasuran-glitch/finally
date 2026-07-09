"""Fixtures for chat/LLM tests: temp DB, seeded cache, fake source, TestClient.

All tests run with LLM_MOCK=true so no real network calls are made.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import state
from app.api import chat
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
    def __init__(self):
        self.added = []
        self.removed = []

    async def add_ticker(self, ticker):
        self.added.append(ticker)

    async def remove_ticker(self, ticker):
        self.removed.append(ticker)


@pytest.fixture
def client(fresh_db, monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "true")
    cache = PriceCache()
    for ticker, price in {"AAPL": 190.0, "GOOGL": 175.0}.items():
        cache.update(ticker, price)
    monkeypatch.setattr(state, "price_cache", cache)
    monkeypatch.setattr(state, "market_source", FakeSource())

    app = FastAPI()
    app.include_router(chat.router)
    return TestClient(app)
