"""Shared application state set during app startup."""

from __future__ import annotations

from app.market import MarketDataSource, PriceCache

price_cache: PriceCache | None = None
market_source: MarketDataSource | None = None
