# Market Data Backend — Detailed Design

## 0. Purpose & Scope

This document is the implementation contract for the market data subsystem described in `PLAN.md` sections 6, 7, and 8. It defines:

- The unified `MarketDataProvider` interface that both implementations conform to
- The in-memory `PriceCache` shared by all providers and consumed by SSE
- The **Simulator** provider (GBM-based, default)
- The **Massive** provider (REST polling, optional, used when `MASSIVE_API_KEY` is set)
- The SSE streaming endpoint that serves prices to the frontend
- Resolutions to the open questions raised in `REVIEW_code.md`:
  - Unknown ticker handling
  - Massive API error/fallback behavior
  - REST-vs-SSE source-of-truth
  - Trade execution vs. price availability

This document is scoped to `backend/app/market_data/` and the price-related parts of `backend/app/api/`. It does not cover portfolio/trade logic beyond the price-availability contract needed by that module.

---

## 1. Directory Layout

```
backend/
└── app/
    └── market_data/
        ├── __init__.py          # exports get_provider(), PriceCache, Quote
        ├── base.py               # MarketDataProvider ABC, Quote dataclass
        ├── cache.py               # PriceCache (thread/async-safe in-memory store)
        ├── simulator.py           # SimulatorProvider (GBM)
        ├── massive.py              # MassiveProvider (REST polling)
        └── seeds.py                # Known ticker seed prices, sector correlation groups
```

`app/api/streaming.py` and `app/api/watchlist.py` depend only on `market_data/__init__.py` (the factory + cache), never on `simulator.py` / `massive.py` directly. This is what makes the two implementations swappable.

---

## 2. The Unified Interface

### 2.1 `Quote` — the shared data shape

Every provider, regardless of source, produces the same shape. This is what gets cached, streamed over SSE, and returned by REST.

```python
# backend/app/market_data/base.py
from __future__ import annotations

import abc
from dataclasses import dataclass
from enum import Enum


class Direction(str, Enum):
    UP = "up"
    DOWN = "down"
    FLAT = "flat"


@dataclass(frozen=True, slots=True)
class Quote:
    """A single price observation for one ticker."""
    ticker: str
    price: float
    prev_price: float
    change_abs: float
    change_pct: float
    direction: Direction
    timestamp: str  # ISO-8601 UTC, e.g. "2026-07-07T14:32:01.123Z"

    @staticmethod
    def build(ticker: str, price: float, prev_price: float, timestamp: str) -> "Quote":
        change_abs = price - prev_price
        if change_abs > 0:
            direction = Direction.UP
        elif change_abs < 0:
            direction = Direction.DOWN
        else:
            direction = Direction.FLAT
        change_pct = (change_abs / prev_price * 100.0) if prev_price else 0.0
        return Quote(
            ticker=ticker,
            price=round(price, 4),
            prev_price=round(prev_price, 4),
            change_abs=round(change_abs, 4),
            change_pct=round(change_pct, 4),
            direction=direction,
            timestamp=timestamp,
        )
```

### 2.2 `MarketDataProvider` — the abstract interface

```python
# backend/app/market_data/base.py (continued)

class MarketDataProvider(abc.ABC):
    """
    Common interface for any market data source.

    Lifecycle:
      1. `start()` is called once at app startup (spawns background task/poller).
      2. `watch(ticker)` / `unwatch(ticker)` are called as the watchlist changes.
      3. `get_quote(ticker)` is called synchronously by REST handlers for
         first-paint snapshots and by the trade endpoint for fill price.
      4. `stop()` is called once at app shutdown for graceful cleanup.

    Implementations MUST write every price update into the shared PriceCache
    (injected at construction) rather than maintaining their own separate
    state, so that `get_quote` and the SSE stream always agree.
    """

    @abc.abstractmethod
    async def start(self) -> None:
        """Begin producing prices in the background (asyncio task)."""

    @abc.abstractmethod
    async def stop(self) -> None:
        """Stop the background task and release resources (HTTP clients, etc.)."""

    @abc.abstractmethod
    async def watch(self, ticker: str) -> Quote:
        """
        Start tracking `ticker`. Must synchronously produce (and cache) an
        initial Quote before returning, so callers never observe a watched
        ticker with no price. Idempotent if already watched.

        Raises UnknownTickerError if the provider cannot produce a price
        for this ticker (only possible for MassiveProvider; see §5.2).
        """

    @abc.abstractmethod
    def unwatch(self, ticker: str) -> None:
        """Stop tracking `ticker`. Idempotent if not currently watched."""

    @abc.abstractmethod
    def get_quote(self, ticker: str) -> Quote | None:
        """Return the last cached Quote for `ticker`, or None if not watched."""

    @abc.abstractmethod
    def tracked_tickers(self) -> set[str]:
        """Return the set of tickers currently being tracked."""


class UnknownTickerError(Exception):
    """Raised when a provider cannot resolve a ticker symbol."""
    def __init__(self, ticker: str):
        self.ticker = ticker
        super().__init__(f"Unknown ticker: {ticker}")
```

### 2.3 Factory — environment-driven selection

```python
# backend/app/market_data/__init__.py
import os

from .base import MarketDataProvider, Quote, Direction, UnknownTickerError
from .cache import PriceCache
from .simulator import SimulatorProvider
from .massive import MassiveProvider

_provider: MarketDataProvider | None = None
_cache = PriceCache()


def get_cache() -> PriceCache:
    return _cache


def get_provider() -> MarketDataProvider:
    """Singleton accessor. Selection is by env var, decided once at import/startup."""
    global _provider
    if _provider is None:
        api_key = os.getenv("MASSIVE_API_KEY", "").strip()
        if api_key:
            _provider = MassiveProvider(api_key=api_key, cache=_cache)
        else:
            _provider = SimulatorProvider(cache=_cache)
    return _provider


__all__ = [
    "MarketDataProvider", "Quote", "Direction", "UnknownTickerError",
    "PriceCache", "get_cache", "get_provider",
]
```

FastAPI startup hook:

```python
# backend/app/main.py (relevant excerpt)
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.market_data import get_provider
from app.db import get_watchlist_tickers  # returns list[str] from SQLite

@asynccontextmanager
async def lifespan(app: FastAPI):
    provider = get_provider()
    await provider.start()
    for ticker in get_watchlist_tickers(user_id="default"):
        await provider.watch(ticker)
    yield
    await provider.stop()

app = FastAPI(lifespan=lifespan)
```

---

## 3. The Shared Price Cache

The cache is the single source of truth that both REST and SSE read from. It is a plain in-process dict guarded by an `asyncio.Lock` (single-process app; no cross-process concerns since SQLite is also single-process here) plus an `asyncio.Condition` so the SSE loop can wait efficiently instead of polling.

```python
# backend/app/market_data/cache.py
import asyncio
from .base import Quote


class PriceCache:
    """
    In-memory latest-quote store, shared by the active provider and every
    open SSE connection. Not persisted — rebuilt from provider seeds on
    every process start, which is fine because prices are ephemeral.
    """

    def __init__(self) -> None:
        self._quotes: dict[str, Quote] = {}
        self._lock = asyncio.Lock()
        self._version = 0
        self._condition = asyncio.Condition()

    async def set(self, quote: Quote) -> None:
        async with self._condition:
            self._quotes[quote.ticker] = quote
            self._version += 1
            self._condition.notify_all()

    def get(self, ticker: str) -> Quote | None:
        return self._quotes.get(ticker)

    def all(self) -> dict[str, Quote]:
        return dict(self._quotes)

    def remove(self, ticker: str) -> None:
        self._quotes.pop(ticker, None)

    async def wait_for_update(self, since_version: int, timeout: float) -> int:
        """
        Block until `_version` advances past `since_version` or `timeout`
        elapses. Returns the current version. Used by the SSE loop so it
        wakes immediately on a price tick instead of polling on a fixed
        interval and risking coalesced/missed updates.
        """
        async with self._condition:
            try:
                await asyncio.wait_for(
                    self._condition.wait_for(lambda: self._version > since_version),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                pass
            return self._version
```

---

## 4. Resolving the Open Questions

These decisions close the gaps flagged in `REVIEW_code.md`.

### 4.1 Unknown tickers (simulator)

**Decision: lazily generate a seed price on first watch.** Restricting to a fixed list would break the "add any ticker via chat" UX in PLAN.md §2/§10. When `SimulatorProvider.watch(ticker)` is called for a ticker not in `seeds.py`, it deterministically derives a plausible seed price from the ticker string (so re-adding the same unknown ticker after removal gives a stable starting point within a session) and assigns it to a synthetic correlation group. See §5.3.

### 4.2 Massive API errors / fallback

**Decision: per-ticker last-known-price freeze, not a global fallback to the simulator.** If a poll fails for a ticker (rate limit, invalid symbol, transient network error), the cache simply keeps serving the last cached `Quote` for that ticker unchanged (`prev_price == price`, i.e., a flat tick is *not* re-emitted — see §6.3) and a `degraded` flag is exposed via `/api/health` (`market_data_status: "ok" | "degraded"`). If a ticker has *never* successfully resolved (e.g., invalid symbol on first watch), `watch()` raises `UnknownTickerError`, which the watchlist endpoint turns into a `422` — the ticker is never added. Mixing simulator data into a "real data" mode would be misleading for a finance app, so we never silently substitute simulated prices for Massive data.

### 4.3 REST vs. SSE source of truth

**Decision: REST (`GET /api/watchlist`, `GET /api/portfolio`) is first-paint only; SSE is authoritative thereafter.** `GET /api/watchlist` returns whatever is currently in the `PriceCache` (a synchronous read, never blocks on network) — this exists purely so the page has numbers to render before the `EventSource` connection finishes its handshake. The frontend does not poll REST for price updates after mount. This is stated explicitly in §7.1 and should be mirrored in the frontend implementation notes.

### 4.4 Trade execution vs. price availability

**Decision: synchronous-watch-then-trade.** `POST /api/portfolio/trade` calls `provider.get_quote(ticker)`; if `None` (ticker not currently watched — e.g., AI orders a trade on a ticker not yet on the watchlist), the trade handler calls `await provider.watch(ticker)` first (which is required to return a fresh quote or raise `UnknownTickerError`), then proceeds with the fill. This means a trade never fails merely because a quote hadn't been fetched yet, while still surfacing a clean `422 Unknown ticker` for genuinely invalid symbols. No trade ever fills on a `None` price.

---

## 5. Simulator Provider (Default)

### 5.1 Model

Each ticker follows **geometric Brownian motion**:

```
S(t+dt) = S(t) * exp( (mu - sigma^2/2) * dt + sigma * sqrt(dt) * Z )
```

where `Z ~ N(0, 1)`. To get correlated moves across sector peers (PLAN.md §6: "tech stocks move together"), each tick draws one shared `Z_sector` per correlation group and blends it with an idiosyncratic `Z_idio` per ticker:

```
Z_ticker = beta * Z_sector + sqrt(1 - beta^2) * Z_idio
```

`beta` (0.6 default) controls how strongly a ticker follows its group.

### 5.2 Seed data

```python
# backend/app/market_data/seeds.py
from dataclasses import dataclass


@dataclass(frozen=True)
class SeedSpec:
    price: float
    mu: float       # annualized drift
    sigma: float    # annualized volatility
    group: str      # correlation group key


SECTOR_GROUPS = ["tech", "auto", "finance", "streaming"]

KNOWN_SEEDS: dict[str, SeedSpec] = {
    "AAPL":  SeedSpec(190.00, 0.08, 0.28, "tech"),
    "GOOGL": SeedSpec(175.00, 0.07, 0.30, "tech"),
    "MSFT":  SeedSpec(420.00, 0.09, 0.24, "tech"),
    "AMZN":  SeedSpec(185.00, 0.10, 0.32, "tech"),
    "TSLA":  SeedSpec(250.00, 0.05, 0.55, "auto"),
    "NVDA":  SeedSpec(130.00, 0.15, 0.45, "tech"),
    "META":  SeedSpec(490.00, 0.09, 0.34, "tech"),
    "JPM":   SeedSpec(200.00, 0.06, 0.20, "finance"),
    "V":     SeedSpec(280.00, 0.07, 0.18, "finance"),
    "NFLX":  SeedSpec(650.00, 0.08, 0.36, "streaming"),
}

EVENT_PROBABILITY_PER_TICK = 0.003   # ~ once every ~11 min at 500ms ticks
EVENT_MIN_PCT = 0.02
EVENT_MAX_PCT = 0.05
```

For an **unknown ticker**, derive a stable synthetic seed instead of rejecting it:

```python
# backend/app/market_data/simulator.py (helper)
import hashlib

def synthesize_seed(ticker: str) -> SeedSpec:
    h = int(hashlib.sha256(ticker.encode()).hexdigest(), 16)
    price = 20.0 + (h % 48000) / 100.0        # $20 - $500 range
    mu = 0.04 + ((h >> 16) % 100) / 1000.0     # 0.04 - 0.14
    sigma = 0.20 + ((h >> 32) % 300) / 1000.0  # 0.20 - 0.50
    group = SECTOR_GROUPS[h % len(SECTOR_GROUPS)]
    return SeedSpec(round(price, 2), mu, sigma, group)
```

### 5.3 Implementation

```python
# backend/app/market_data/simulator.py
import asyncio
import math
import random
from datetime import datetime, timezone

from .base import MarketDataProvider, Quote, UnknownTickerError
from .cache import PriceCache
from .seeds import KNOWN_SEEDS, SeedSpec, EVENT_PROBABILITY_PER_TICK, EVENT_MIN_PCT, EVENT_MAX_PCT

TICK_SECONDS = 0.5


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class SimulatorProvider(MarketDataProvider):
    def __init__(self, cache: PriceCache, seed: int | None = None) -> None:
        self._cache = cache
        self._specs: dict[str, SeedSpec] = {}
        self._prices: dict[str, float] = {}
        self._rng = random.Random(seed)
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def watch(self, ticker: str) -> Quote:
        ticker = ticker.upper()
        if ticker in self._specs:
            return self._cache.get(ticker)  # already tracked

        spec = KNOWN_SEEDS.get(ticker) or synthesize_seed(ticker)
        self._specs[ticker] = spec
        self._prices[ticker] = spec.price

        quote = Quote.build(ticker, spec.price, spec.price, _now_iso())
        await self._cache.set(quote)
        return quote

    def unwatch(self, ticker: str) -> None:
        ticker = ticker.upper()
        self._specs.pop(ticker, None)
        self._prices.pop(ticker, None)
        self._cache.remove(ticker)

    def get_quote(self, ticker: str):
        return self._cache.get(ticker.upper())

    def tracked_tickers(self) -> set[str]:
        return set(self._specs.keys())

    async def _run_loop(self) -> None:
        dt_years = TICK_SECONDS / (60 * 60 * 24 * 252)  # trading-year fraction
        while True:
            await asyncio.sleep(TICK_SECONDS)
            if not self._specs:
                continue

            group_shocks = {
                group: self._rng.gauss(0, 1)
                for group in {s.group for s in self._specs.values()}
            }

            for ticker, spec in list(self._specs.items()):
                prev = self._prices[ticker]
                z_idio = self._rng.gauss(0, 1)
                beta = 0.6
                z = beta * group_shocks[spec.group] + math.sqrt(1 - beta**2) * z_idio

                drift = (spec.mu - 0.5 * spec.sigma**2) * dt_years
                diffusion = spec.sigma * math.sqrt(dt_years) * z
                new_price = prev * math.exp(drift + diffusion)

                if self._rng.random() < EVENT_PROBABILITY_PER_TICK:
                    pct = self._rng.uniform(EVENT_MIN_PCT, EVENT_MAX_PCT)
                    new_price *= (1 + pct) if self._rng.random() < 0.5 else (1 - pct)

                new_price = max(new_price, 0.01)
                self._prices[ticker] = new_price

                quote = Quote.build(ticker, new_price, prev, _now_iso())
                await self._cache.set(quote)
```

---

## 6. Massive Provider (Optional, Real Data)

### 6.1 Interface fit

`MassiveProvider` implements the same `watch/unwatch/get_quote/tracked_tickers` surface, but instead of an internal GBM loop, it runs a polling task that batches all currently-watched tickers into one REST call per interval.

### 6.2 Poll interval

Per PLAN.md §6, interval scales with tier. Configurable via `MASSIVE_POLL_SECONDS` env var, default `15` (free-tier safe: 5 calls/min → one call every 12s minimum, 15s gives margin).

### 6.3 Implementation

```python
# backend/app/market_data/massive.py
import asyncio
import os
from datetime import datetime, timezone

import httpx

from .base import MarketDataProvider, Quote, UnknownTickerError
from .cache import PriceCache

MASSIVE_BASE_URL = "https://api.massive.dev/v1"  # placeholder; see provider docs
DEFAULT_POLL_SECONDS = int(os.getenv("MASSIVE_POLL_SECONDS", "15"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class MassiveProvider(MarketDataProvider):
    def __init__(self, api_key: str, cache: PriceCache, poll_seconds: int = DEFAULT_POLL_SECONDS) -> None:
        self._api_key = api_key
        self._cache = cache
        self._poll_seconds = poll_seconds
        self._tickers: set[str] = set()
        self._prev_prices: dict[str, float] = {}
        self._client: httpx.AsyncClient | None = None
        self._task: asyncio.Task | None = None
        self.degraded: bool = False

    async def start(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=MASSIVE_BASE_URL,
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=10.0,
        )
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._client:
            await self._client.aclose()

    async def watch(self, ticker: str) -> Quote:
        ticker = ticker.upper()
        if ticker in self._tickers:
            cached = self._cache.get(ticker)
            if cached:
                return cached
        # Synchronously resolve one quote so callers never see a gap.
        quote = await self._fetch_one(ticker)
        self._tickers.add(ticker)
        self._prev_prices[ticker] = quote.price
        await self._cache.set(quote)
        return quote

    def unwatch(self, ticker: str) -> None:
        ticker = ticker.upper()
        self._tickers.discard(ticker)
        self._prev_prices.pop(ticker, None)
        self._cache.remove(ticker)

    def get_quote(self, ticker: str):
        return self._cache.get(ticker.upper())

    def tracked_tickers(self) -> set[str]:
        return set(self._tickers)

    async def _fetch_one(self, ticker: str) -> Quote:
        resp = await self._client.get("/quote", params={"symbol": ticker})
        if resp.status_code == 404:
            raise UnknownTickerError(ticker)
        resp.raise_for_status()
        data = resp.json()
        price = float(data["price"])
        prev = float(data.get("prev_close", price))
        return Quote.build(ticker, price, prev, _now_iso())

    async def _run_loop(self) -> None:
        while True:
            await asyncio.sleep(self._poll_seconds)
            if not self._tickers:
                continue
            try:
                await self._poll_batch()
                self.degraded = False
            except (httpx.HTTPError, KeyError, ValueError):
                # Network/parse failure: keep serving last-known prices.
                # Do not crash the loop; try again next interval.
                self.degraded = True

    async def _poll_batch(self) -> None:
        symbols = ",".join(sorted(self._tickers))
        resp = await self._client.get("/quotes", params={"symbols": symbols})
        resp.raise_for_status()
        payload = resp.json()  # { "results": [ {symbol, price, prev_close}, ... ] }

        seen = set()
        for row in payload.get("results", []):
            ticker = row["symbol"].upper()
            if ticker not in self._tickers:
                continue
            seen.add(ticker)
            price = float(row["price"])
            prev = self._prev_prices.get(ticker, price)
            quote = Quote.build(ticker, price, prev, _now_iso())
            self._prev_prices[ticker] = price
            await self._cache.set(quote)

        # Tickers Massive silently dropped (rate-limited / bad symbol on this
        # pass) simply keep their last cached Quote — no update emitted,
        # no crash. `self.degraded` is set by the caller on hard failures;
        # partial omissions like this are logged but not fatal.
        missing = self._tickers - seen
        if missing:
            self.degraded = True
```

> **Note:** `MASSIVE_BASE_URL` and the exact request/response shape are placeholders pending the real Massive/Polygon.io API reference. The `_fetch_one` / `_poll_batch` methods are the only two places that need updating once the actual endpoint contract is confirmed — everything above them (cache, SSE, interface) is agnostic to that detail, which is the point of the shared interface.

---

## 7. API Endpoints

### 7.1 `GET /api/watchlist` — first-paint snapshot

```python
# backend/app/api/watchlist.py
from fastapi import APIRouter, HTTPException
from app.market_data import get_provider, get_cache, UnknownTickerError
from app.db import add_watchlist_ticker, remove_watchlist_ticker, list_watchlist_tickers

router = APIRouter(prefix="/api/watchlist")


@router.get("")
async def get_watchlist():
    """
    Synchronous cache read — used only for first paint before the SSE
    connection is established. The frontend must not poll this endpoint
    on an interval; EventSource is the source of truth after mount.
    """
    tickers = list_watchlist_tickers(user_id="default")
    cache = get_cache()
    return [
        cache.get(t) or {"ticker": t, "price": None, "prev_price": None,
                          "change_abs": None, "change_pct": None,
                          "direction": "flat", "timestamp": None}
        for t in tickers
    ]


@router.post("")
async def add_ticker(body: dict):
    ticker = body["ticker"].upper().strip()
    provider = get_provider()
    try:
        quote = await provider.watch(ticker)
    except UnknownTickerError:
        raise HTTPException(422, detail=f"Unknown ticker: {ticker}")
    add_watchlist_ticker(user_id="default", ticker=ticker)
    return quote


@router.delete("/{ticker}")
async def remove_ticker(ticker: str):
    ticker = ticker.upper()
    remove_watchlist_ticker(user_id="default", ticker=ticker)
    # Only unwatch if no other reason to track it (e.g., an open position).
    if not has_open_position(user_id="default", ticker=ticker):
        get_provider().unwatch(ticker)
    return {"ok": True}
```

`has_open_position` guards against unwatching a ticker the user still holds shares in — prices for held positions must keep updating for P&L even if removed from the watchlist. (This detail belongs to the portfolio module but is called out here since it affects provider lifecycle.)

### 7.2 `GET /api/stream/prices` — SSE

```python
# backend/app/api/streaming.py
import asyncio
import json
from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse
from app.market_data import get_cache

router = APIRouter(prefix="/api/stream")

SSE_POLL_TIMEOUT = 1.0  # seconds; how often to check for client disconnect


@router.get("/prices")
async def stream_prices(request: Request):
    cache = get_cache()

    async def event_generator():
        # Send the current snapshot immediately so a fresh tab doesn't
        # wait a full tick before rendering anything.
        for quote in cache.all().values():
            yield {"event": "price", "data": json.dumps(quote.__dict__, default=str)}

        version = 0
        while True:
            if await request.is_disconnected():
                break
            version = await cache.wait_for_update(version, timeout=SSE_POLL_TIMEOUT)
            # Emit whatever changed since the last version. For simplicity
            # (and because ticks are ~500ms), we just re-diff the full set;
            # watchlist sizes here are small (tens of tickers), so this is cheap.
            for quote in cache.all().values():
                yield {"event": "price", "data": json.dumps(quote.__dict__, default=str)}

    return EventSourceResponse(event_generator())
```

Frontend consumption (per PLAN.md §10):

```ts
const es = new EventSource("/api/stream/prices");
es.addEventListener("price", (e) => {
  const quote = JSON.parse(e.data);
  applyPriceUpdate(quote); // triggers flash animation + sparkline append
});
```

`EventSource` handles reconnection natively; on reconnect the generator immediately re-sends the full current snapshot, so the client always resyncs correctly (satisfies the E2E "SSE resilience" scenario in PLAN.md §12).

### 7.3 `GET /api/health`

```python
@router.get("/health")
async def health():
    provider = get_provider()
    status = "degraded" if getattr(provider, "degraded", False) else "ok"
    return {"status": "ok", "market_data_status": status}
```

---

## 8. Testing Strategy (backend/tests/market_data/)

Per PLAN.md §12:

- **`test_simulator.py`**
  - `watch()` returns a `Quote` synchronously with `price == prev_price` on first call.
  - Repeated `watch()` on the same ticker is idempotent (no duplicate state, returns cached quote).
  - Unknown ticker produces a deterministic, stable synthetic seed (`synthesize_seed("XYZ")` called twice returns identical values).
  - Over N simulated ticks, prices stay `> 0` and within a sane multiple of seed (no runaway blowup) for reasonable sigma values.
  - Tickers in the same `group` exhibit positive correlation over many ticks (statistical test on sign agreement).
- **`test_cache.py`**
  - `set()` then `get()` round-trips.
  - `wait_for_update()` returns promptly after a `set()` from another task; returns via timeout when no update occurs.
- **`test_massive.py`** (using `httpx.MockTransport` / `respx`)
  - `_fetch_one` raises `UnknownTickerError` on a 404.
  - `_poll_batch` updates cache for returned symbols and leaves others untouched (frozen) when omitted from the response.
  - A raised `HTTPError` during polling sets `degraded = True` and does not crash `_run_loop` (next iteration still runs).
- **`test_interface_conformance.py`**
  - Parametrized over `[SimulatorProvider, MassiveProvider(mocked transport)]` asserting both satisfy: `watch` before `get_quote` is non-`None`; `unwatch` then `get_quote` is `None`; `tracked_tickers()` reflects watch/unwatch calls.

---

## 9. Summary of Decisions Table

| Question (from REVIEW_code.md) | Decision |
|---|---|
| Unknown ticker in simulator | Synthesize a deterministic seed on first `watch()`; never reject |
| Massive per-ticker fetch failure | Freeze last cached price for that ticker; don't crash the poll loop |
| Massive can't resolve a symbol at all | `UnknownTickerError` → `422` on `POST /api/watchlist`, ticker never added |
| Never mix simulator prices into Massive mode | Confirmed — no cross-provider fallback, only degraded-status flag |
| REST vs SSE source of truth | REST = first paint snapshot only; SSE = authoritative stream after mount |
| Trade fill with no cached price | Trade handler calls `provider.watch(ticker)` synchronously before fill; only fails on genuine `UnknownTickerError` |
