"""Watchlist queries and mutations — shared by REST routes and chat."""

from __future__ import annotations

from app import state
from app.db import repository as repo


def get_watchlist() -> list[dict]:
    """Return watched tickers joined with their latest cached prices."""
    entries = []
    for ticker in repo.list_watchlist():
        update = state.price_cache.get(ticker)
        if update is not None:
            entries.append(
                {
                    "ticker": ticker,
                    "price": update.price,
                    "previous_price": update.previous_price,
                    "change": update.change,
                    "change_percent": update.change_percent,
                    "direction": update.direction,
                }
            )
        else:
            entries.append(
                {
                    "ticker": ticker,
                    "price": None,
                    "previous_price": None,
                    "change": None,
                    "change_percent": None,
                    "direction": "flat",
                }
            )
    return entries


async def add_ticker(ticker: str) -> None:
    """Add a ticker to the watchlist and start tracking its price."""
    ticker = ticker.upper()
    repo.add_to_watchlist(ticker)
    await state.market_source.add_ticker(ticker)


async def remove_ticker(ticker: str) -> None:
    """Remove a ticker from the watchlist and stop tracking its price."""
    ticker = ticker.upper()
    repo.remove_from_watchlist(ticker)
    await state.market_source.remove_ticker(ticker)
