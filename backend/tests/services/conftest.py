"""Fixtures for service-layer tests: temp DB plus a seeded price cache."""

import pytest

from app import state
from app.db import connection
from app.market import PriceCache


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Point FINALLY_DB_PATH at a fresh temp file and reset the init guard."""
    path = tmp_path / "finally.db"
    monkeypatch.setenv("FINALLY_DB_PATH", str(path))
    connection._initialized.clear()
    yield path
    connection._initialized.clear()


@pytest.fixture
def cache(monkeypatch):
    """Install a PriceCache with seeded prices into app.state."""
    c = PriceCache()
    for ticker, price in {"AAPL": 190.0, "GOOGL": 175.0, "MSFT": 400.0}.items():
        c.update(ticker, price)
    monkeypatch.setattr(state, "price_cache", c)
    return c
