# Market Data Backend — Detailed Design

## 0. Purpose & Scope

This document is the **implementation contract** for the market data subsystem described in `PLAN.md` sections 6, 7, and 8. It is the authoritative, detailed synthesis of three supporting sketches — `MARKET_INTERFACE.md` (the abstract interface), `MARKET_SIMULATOR.md` (the GBM simulator), and `MASSIVE_API.md` (the real Massive/Polygon.io REST API). Where those sketches disagree with each other (naming, module paths, correlation math, the Massive request shape), **this document wins**; §11 records exactly what it supersedes.

It defines, with ready-to-implement code:

- The unified `MarketDataProvider` interface and the shared `Quote` shape that both implementations conform to
- The in-memory `PriceCache` shared by all providers and consumed by SSE
- The **Simulator** provider (GBM + Cholesky-correlated moves, default)
- The **Massive** provider (REST polling via the `massive` client, optional, used when `MASSIVE_API_KEY` is set)
- The SSE streaming endpoint that serves prices to the frontend
- Worked end-to-end flows (§8)
- Resolutions to every open question raised in `REVIEW_code.md` and `REVIEW.md`:
  - Unknown ticker handling
  - Massive API error / fallback behavior
  - REST-vs-SSE source-of-truth
  - Trade execution vs. price availability
  - Daily-change-% vs. per-tick flash (both are needed by PLAN §10)

This document is scoped to `backend/app/market_data/` and the price-related parts of `backend/app/api/`. It does not cover portfolio/trade logic beyond the price-availability contract that module depends on.

---

## 1. Directory Layout

```
backend/
└── app/
    └── market_data/
        ├── __init__.py          # exports get_provider(), get_cache(), Quote, Direction, ...
        ├── base.py              # MarketDataProvider ABC, Quote dataclass, Direction, errors
        ├── cache.py             # PriceCache (async-safe in-memory store + update signal)
        ├── seeds.py             # Known ticker seed specs, correlation model, event params
        ├── simulator.py         # GBMSimulator + SimulatorProvider (GBM, default)
        └── massive.py           # MassiveProvider (REST polling via `massive` client)
```

`app/api/streaming.py`, `app/api/watchlist.py`, and the portfolio/trade handler depend **only** on `market_data/__init__.py` (the factory + cache) — never on `simulator.py` / `massive.py` directly. That single seam is what makes the two implementations swappable by flipping one env var.

### Dependencies added to `backend/pyproject.toml`

```toml
[project]
dependencies = [
    # ... existing (fastapi, uvicorn, etc.) ...
    "numpy>=1.26",            # Cholesky correlation in the simulator
    "massive>=1.0",           # official Massive/Polygon.io client (real-data mode)
    "sse-starlette>=2.1",     # EventSourceResponse for the SSE endpoint
    "httpx>=0.27",            # transitive via massive; pinned for test mocking (respx)
]
```

> `numpy` is only exercised by the simulator and `massive` only by the real-data provider, but both are declared unconditionally so the single Docker image can run in either mode without a rebuild.

---

## 2. The Unified Interface

### 2.1 `Quote` — the shared data shape

Every provider, regardless of source, produces the **same** shape. This is what gets cached, streamed over SSE, and returned by REST. It carries **two** reference prices so the frontend can satisfy both PLAN §10 requirements at once:

- **`prev_price`** — the immediately preceding tick's price. Drives `direction`, i.e. the green/red **flash** animation (tick-over-tick).
- **`prev_close`** — the day's reference close. Drives `change_abs` / `change_pct`, i.e. the **"daily change %"** column shown in the watchlist.

```python
# backend/app/market_data/base.py
from __future__ import annotations

import abc
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum


class Direction(str, Enum):
    UP = "up"
    DOWN = "down"
    FLAT = "flat"


def now_iso() -> str:
    """Current UTC time as ISO-8601 with millisecond precision, e.g.
    '2026-07-07T14:32:01.123Z'. Shared by both providers for timestamps."""
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def iso_from_epoch_ms(ms: int) -> str:
    """Convert a Unix-millisecond timestamp (as Massive returns) to ISO-8601 UTC."""
    return (
        datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


@dataclass(frozen=True, slots=True)
class Quote:
    """A single price observation for one ticker.

    Field semantics (important — the frontend relies on the split):
      price       current price (fill price for trades, big number in the UI)
      prev_price  previous *tick's* price -> drives `direction` -> flash color
      prev_close  day reference close      -> drives change_abs / change_pct
      change_abs  price - prev_close       (absolute day change)
      change_pct  day change in percent
      direction   up/down/flat vs prev_price (per-tick, for the flash animation)
      timestamp   ISO-8601 UTC of this observation
    """
    ticker: str
    price: float
    prev_price: float
    prev_close: float
    change_abs: float
    change_pct: float
    direction: Direction
    timestamp: str

    @staticmethod
    def build(
        ticker: str,
        price: float,
        prev_price: float,
        prev_close: float,
        timestamp: str | None = None,
    ) -> "Quote":
        tick_delta = price - prev_price
        if tick_delta > 0:
            direction = Direction.UP
        elif tick_delta < 0:
            direction = Direction.DOWN
        else:
            direction = Direction.FLAT

        change_abs = price - prev_close
        change_pct = (change_abs / prev_close * 100.0) if prev_close else 0.0

        return Quote(
            ticker=ticker.upper(),
            price=round(price, 4),
            prev_price=round(prev_price, 4),
            prev_close=round(prev_close, 4),
            change_abs=round(change_abs, 4),
            change_pct=round(change_pct, 4),
            direction=direction,
            timestamp=timestamp or now_iso(),
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["direction"] = self.direction.value  # Enum -> plain string for JSON
        return d
```

**Wire shape** (one SSE `price` event, or one element of the `GET /api/watchlist` array):

```json
{
  "ticker": "AAPL",
  "price": 190.42,
  "prev_price": 190.31,
  "prev_close": 189.10,
  "change_abs": 1.32,
  "change_pct": 0.6981,
  "direction": "up",
  "timestamp": "2026-07-07T14:32:01.123Z"
}
```

### 2.2 `MarketDataProvider` — the abstract interface

```python
# backend/app/market_data/base.py (continued)

class MarketDataProvider(abc.ABC):
    """
    Common interface for any market data source.

    Lifecycle:
      1. `start()`  — called once at app startup; spawns the background task
                      (GBM loop or REST poller).
      2. `watch(t)` / `unwatch(t)` — called as the watchlist (or an open
                      position) changes.
      3. `get_quote(t)` — called synchronously by REST handlers for first-paint
                      snapshots and by the trade endpoint for the fill price.
      4. `stop()`   — called once at app shutdown for graceful cleanup.

    Contract: implementations MUST write every price update into the shared
    PriceCache (injected at construction) rather than keeping a second copy of
    state that callers read. `get_quote` and the SSE stream therefore always
    agree, because both read the one cache.
    """

    @abc.abstractmethod
    async def start(self) -> None:
        """Begin producing prices in the background (an asyncio task)."""

    @abc.abstractmethod
    async def stop(self) -> None:
        """Stop the background task and release resources (HTTP clients, etc.)."""

    @abc.abstractmethod
    async def watch(self, ticker: str) -> Quote:
        """
        Start tracking `ticker`. MUST synchronously produce (and cache) an
        initial Quote before returning, so a caller never observes a watched
        ticker with no price. Idempotent: a second call returns the cached Quote.

        Raises UnknownTickerError if the provider cannot resolve a price for
        this ticker (only possible for MassiveProvider; the simulator always
        synthesizes one — see §4.1).
        """

    @abc.abstractmethod
    def unwatch(self, ticker: str) -> None:
        """Stop tracking `ticker` and drop it from the cache. Idempotent."""

    @abc.abstractmethod
    def get_quote(self, ticker: str) -> Quote | None:
        """Return the last cached Quote for `ticker`, or None if not tracked.
        Synchronous and non-blocking — never performs I/O."""

    @abc.abstractmethod
    def tracked_tickers(self) -> set[str]:
        """The set of tickers currently being tracked."""

    @property
    def degraded(self) -> bool:
        """True when the source is not currently producing fresh prices
        (e.g. Massive polling is failing). Surfaced by /api/health. The
        simulator is never degraded; the base default is False."""
        return False


class MarketDataError(Exception):
    """Base class for market-data errors."""


class UnknownTickerError(MarketDataError):
    """Raised when a provider cannot resolve a ticker symbol at all."""

    def __init__(self, ticker: str):
        self.ticker = ticker.upper()
        super().__init__(f"Unknown ticker: {self.ticker}")
```

> **Interface note.** This `MarketDataProvider` supersedes the `MarketDataSource` sketch in `MARKET_INTERFACE.md`. The differences are deliberate: (a) `watch()` returns a `Quote` and is **synchronous-resolving** so the "trade a just-added ticker" and "first paint" flows never race an empty cache; (b) a `degraded` signal is part of the contract; (c) `get_quote()` exists so REST/trade handlers read a single quote without scanning the whole cache.

### 2.3 Factory — environment-driven selection

```python
# backend/app/market_data/__init__.py
import os

from .base import (
    Direction,
    MarketDataError,
    MarketDataProvider,
    Quote,
    UnknownTickerError,
)
from .cache import PriceCache
from .massive import MassiveProvider
from .simulator import SimulatorProvider

_cache = PriceCache()
_provider: MarketDataProvider | None = None


def get_cache() -> PriceCache:
    return _cache


def get_provider() -> MarketDataProvider:
    """Process-wide singleton. Source is chosen once, by env var:
    a non-empty MASSIVE_API_KEY selects real data; otherwise the simulator."""
    global _provider
    if _provider is None:
        api_key = os.getenv("MASSIVE_API_KEY", "").strip()
        if api_key:
            _provider = MassiveProvider(api_key=api_key, cache=_cache)
        else:
            _provider = SimulatorProvider(cache=_cache)
    return _provider


def reset_provider_for_tests() -> None:
    """Test helper: drop the singleton so a test can re-select the source."""
    global _provider
    _provider = None
    _cache.clear()


__all__ = [
    "MarketDataProvider", "Quote", "Direction",
    "MarketDataError", "UnknownTickerError",
    "PriceCache", "get_cache", "get_provider", "reset_provider_for_tests",
]
```

### 2.4 FastAPI startup wiring

```python
# backend/app/main.py (relevant excerpt)
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import list_watchlist_tickers, list_position_tickers
from app.market_data import get_provider, UnknownTickerError


@asynccontextmanager
async def lifespan(app: FastAPI):
    provider = get_provider()
    await provider.start()
    # Warm the cache for everything we must price on first paint: the watchlist
    # plus any tickers the user holds a position in (P&L needs live prices even
    # if a held ticker was removed from the watchlist).
    seed_tickers = set(list_watchlist_tickers("default")) | set(list_position_tickers("default"))
    for ticker in seed_tickers:
        try:
            await provider.watch(ticker)
        except UnknownTickerError:
            # A previously-valid symbol that Massive no longer resolves: skip it
            # rather than crash startup. It simply won't stream until re-added.
            continue
    yield
    await provider.stop()


app = FastAPI(lifespan=lifespan)
```

---

## 3. The Shared Price Cache

The cache is the single source of truth that both REST and SSE read from. It is a plain in-process dict guarded by an `asyncio.Condition` (the app is single-process; SQLite is single-process too, so there are no cross-process concerns). The `Condition` lets each SSE loop **wait to be woken** on the next tick instead of busy-polling on a fixed 500 ms timer — which avoids both wasted wakeups and coalesced/missed updates.

> **Why `asyncio.Condition`, not `threading.Lock`.** The `MARKET_INTERFACE.md` sketch used a `threading.Lock`. Everything here runs in one asyncio event loop (providers use `asyncio.create_task`; the Massive client's *blocking* calls are offloaded with `asyncio.to_thread`, and the cache is only ever mutated back on the loop). An `asyncio.Condition` is the right primitive: it's cheap, it never blocks the loop, and it gives us the "wake the SSE generators" signal for free.

```python
# backend/app/market_data/cache.py
import asyncio

from .base import Quote


class PriceCache:
    """
    In-memory latest-quote store, shared by the active provider and every open
    SSE connection. Not persisted — rebuilt from provider seeds on every process
    start, which is fine because prices are ephemeral.

    A monotonically increasing `version` counter is bumped on every `set()`.
    SSE loops record the version they last emitted and call `wait_for_update`
    to sleep until the counter moves, so they push exactly when data changes.
    """

    def __init__(self) -> None:
        self._quotes: dict[str, Quote] = {}
        self._version = 0
        self._condition = asyncio.Condition()

    @property
    def version(self) -> int:
        return self._version

    async def set(self, quote: Quote) -> None:
        async with self._condition:
            self._quotes[quote.ticker] = quote
            self._version += 1
            self._condition.notify_all()

    def get(self, ticker: str) -> Quote | None:
        return self._quotes.get(ticker.upper())

    def all(self) -> dict[str, Quote]:
        return dict(self._quotes)

    def remove(self, ticker: str) -> None:
        self._quotes.pop(ticker.upper(), None)

    def clear(self) -> None:
        self._quotes.clear()
        self._version = 0

    async def wait_for_update(self, since_version: int, timeout: float) -> int:
        """
        Block until `version` advances past `since_version`, or `timeout`
        elapses. Returns the current version either way. Used by the SSE loop
        so it wakes on a tick instead of polling, while `timeout` still bounds
        how quickly it notices a client disconnect.
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

> **Note on `set()` from a worker thread.** The Massive provider does its blocking HTTP in a thread (`asyncio.to_thread`) but returns the parsed rows to the event loop and calls `await cache.set(...)` *there*. The cache is thus only ever mutated from the loop, so the `asyncio.Condition` is always used correctly.

---

## 4. Resolving the Open Questions

These decisions close every gap flagged in `REVIEW_code.md` (and the market-data items in `REVIEW.md`).

### 4.1 Unknown tickers (simulator) — *synthesize, never reject*

Restricting to a fixed list would break the "add any ticker via the UI or chat" UX in `PLAN.md` §2/§10. When `SimulatorProvider.watch(ticker)` is called for a symbol not in `seeds.py`, it **deterministically derives a plausible seed spec from the ticker string** (§5.4). Determinism matters: re-adding `XYZ` after removing it gives the same starting point within a run, so charts don't jump. The synthetic ticker is assigned to a synthetic correlation group so it still participates in correlated moves.

### 4.2 Massive API errors / fallback — *per-ticker freeze + degraded flag, never mix in sim data*

If a poll fails (rate limit `429`, transient network error, `5xx`), the cache keeps serving the **last cached `Quote`** for each affected ticker unchanged, and `provider.degraded` flips to `True` (surfaced via `/api/health`). We do **not** silently substitute simulated prices into "real data" mode — that would be misleading for a finance app. If a symbol has **never** resolved (invalid symbol on first `watch()`), `watch()` raises `UnknownTickerError` → `422`, and the ticker is never added. See §6.4.

### 4.3 REST vs. SSE source of truth — *REST is first-paint only; SSE is authoritative*

`GET /api/watchlist` (and `GET /api/portfolio`) return whatever is currently in the `PriceCache` — a synchronous, non-blocking read. This exists purely so the page has numbers to render before the `EventSource` handshake completes. **The frontend must not poll REST for prices after mount**; `EventSource` is the source of truth thereafter (§7.1, §7.2).

### 4.4 Trade execution vs. price availability — *synchronous-watch-then-fill*

`POST /api/portfolio/trade` calls `provider.get_quote(ticker)`; if `None` (e.g. the AI orders a trade on a ticker not yet watched), the handler calls `await provider.watch(ticker)` first — which is contractually required to return a fresh quote or raise `UnknownTickerError` — then fills at that price. A trade therefore never fails merely because a quote hadn't been fetched yet, while a genuinely invalid symbol still yields a clean `422`. **No trade ever fills on a `None` price** (§8.3).

### 4.5 Daily change % vs. per-tick flash — *both, via `prev_close` + `prev_price`*

PLAN §10 asks for a "daily change %" column **and** a per-tick green/red flash. `Quote` carries both references (§2.1): `change_pct` is measured against `prev_close` (the day baseline) for the column; `direction` is measured against `prev_price` (the previous tick) for the flash. The simulator uses each ticker's **session-open price** as `prev_close`; Massive uses `day.previous_close` from the snapshot.

---

## 5. Simulator Provider (Default)

### 5.1 Model

Each ticker follows **geometric Brownian motion** (the Black–Scholes price process — multiplicative, so prices can never go negative):

```
S(t+dt) = S(t) * exp( (mu - sigma^2/2) * dt + sigma * sqrt(dt) * Z )
```

- `mu` — annualized drift (expected return)
- `sigma` — annualized volatility
- `dt` — time step as a fraction of a trading year
- `Z ~ N(0, 1)` — a (correlated) standard-normal draw

**Time step.** Updates run every 500 ms against a ~252-day, ~6.5-hour trading year:

```
dt = 0.5 / (252 * 6.5 * 3600) ≈ 8.5e-8
```

This tiny `dt` yields small, realistic sub-cent per-tick moves that accumulate naturally over a session.

### 5.2 Correlated moves (Cholesky)

Real sector peers move together (`PLAN.md` §6: "tech stocks move together"). We build a correlation matrix `C` over the currently-tracked tickers, take its Cholesky factor `L = cholesky(C)`, and turn independent normals `Z_indep` into correlated ones:

```
Z_corr = L @ Z_indep
```

Cholesky guarantees the result is positive semi-definite for any valid correlation matrix. `L` is rebuilt whenever the tracked set changes — `O(n²)` but `n` is small (tens of tickers). Default pairwise correlations:

| Pair | ρ |
|---|---|
| Tech ↔ Tech (AAPL, GOOGL, MSFT, AMZN, META, NVDA, NFLX) | 0.60 |
| Finance ↔ Finance (JPM, V) | 0.50 |
| TSLA ↔ anything (a loner) | 0.30 |
| Cross-sector / unknown | 0.30 |

### 5.3 Random events

Every tick, each ticker has a small probability of a sudden 2–5 % jump — drama that keeps the dashboard alive:

```python
if rng.random() < EVENT_PROBABILITY_PER_TICK:
    shock = rng.uniform(EVENT_MIN_PCT, EVENT_MAX_PCT) * rng.choice([-1, 1])
    price *= (1 + shock)
```

At `0.001`/tick and 500 ms ticks that's ~one event per ticker every ~8 min; across 10 tickers, something dramatic roughly once a minute.

### 5.4 Seed data & synthetic seeds

```python
# backend/app/market_data/seeds.py
from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class SeedSpec:
    price: float    # session-open price (also used as prev_close baseline)
    mu: float       # annualized drift
    sigma: float    # annualized volatility
    group: str      # correlation-group key


# Sector membership drives the correlation matrix (see correlation()).
TECH = {"AAPL", "GOOGL", "MSFT", "AMZN", "META", "NVDA", "NFLX"}
FINANCE = {"JPM", "V"}
SYNTHETIC_GROUPS = ["tech", "auto", "finance", "streaming"]

KNOWN_SEEDS: dict[str, SeedSpec] = {
    "AAPL":  SeedSpec(190.00, 0.05, 0.22, "tech"),
    "GOOGL": SeedSpec(175.00, 0.05, 0.25, "tech"),
    "MSFT":  SeedSpec(420.00, 0.05, 0.20, "tech"),
    "AMZN":  SeedSpec(185.00, 0.05, 0.28, "tech"),
    "TSLA":  SeedSpec(250.00, 0.03, 0.50, "auto"),      # high vol, loner
    "NVDA":  SeedSpec(130.00, 0.08, 0.40, "tech"),      # high vol, strong drift
    "META":  SeedSpec(490.00, 0.05, 0.30, "tech"),
    "JPM":   SeedSpec(200.00, 0.04, 0.18, "finance"),   # low vol (bank)
    "V":     SeedSpec(280.00, 0.04, 0.17, "finance"),   # low vol (payments)
    "NFLX":  SeedSpec(650.00, 0.05, 0.35, "streaming"),
}

DEFAULT_SPEC = SeedSpec(100.00, 0.05, 0.25, "tech")

EVENT_PROBABILITY_PER_TICK = 0.001   # ~ one event per ticker every ~8 min at 500ms
EVENT_MIN_PCT = 0.02
EVENT_MAX_PCT = 0.05

TICK_SECONDS = 0.5
DT_YEARS = TICK_SECONDS / (252 * 6.5 * 3600)   # ≈ 8.5e-8


def synthesize_seed(ticker: str) -> SeedSpec:
    """Deterministically derive a plausible SeedSpec for an unknown ticker.
    Same symbol -> same spec within and across runs, so re-adding a ticker is
    stable. See §4.1."""
    h = int(hashlib.sha256(ticker.upper().encode()).hexdigest(), 16)
    price = 20.0 + (h % 48000) / 100.0          # $20 – $500
    mu = 0.04 + ((h >> 16) % 100) / 1000.0       # 0.04 – 0.14
    sigma = 0.20 + ((h >> 32) % 300) / 1000.0    # 0.20 – 0.50
    group = SYNTHETIC_GROUPS[h % len(SYNTHETIC_GROUPS)]
    return SeedSpec(round(price, 2), mu, sigma, group)


def spec_for(ticker: str) -> SeedSpec:
    return KNOWN_SEEDS.get(ticker.upper(), None) or synthesize_seed(ticker)


def correlation(t1: str, t2: str) -> float:
    """Pairwise correlation used to build the Cholesky matrix."""
    if t1 == t2:
        return 1.0
    t1, t2 = t1.upper(), t2.upper()
    if t1 == "TSLA" or t2 == "TSLA":
        return 0.30
    if t1 in TECH and t2 in TECH:
        return 0.60
    if t1 in FINANCE and t2 in FINANCE:
        return 0.50
    return 0.30
```

### 5.5 The GBM engine

`GBMSimulator` is the pure-math core: it holds prices and params, and `step()` advances everything one tick. It has no knowledge of the cache, asyncio, or `Quote` — which makes it trivially unit-testable.

```python
# backend/app/market_data/simulator.py
from __future__ import annotations

import asyncio
import math
import random

import numpy as np

from .base import MarketDataProvider, Quote, now_iso
from .cache import PriceCache
from .seeds import (
    DT_YEARS,
    EVENT_MAX_PCT,
    EVENT_MIN_PCT,
    EVENT_PROBABILITY_PER_TICK,
    TICK_SECONDS,
    SeedSpec,
    correlation,
    spec_for,
)


class GBMSimulator:
    """Generates correlated GBM price paths for a dynamic set of tickers.
    Pure computation — no I/O, no asyncio, no cache. `seed` makes runs
    reproducible in tests."""

    def __init__(self, seed: int | None = None) -> None:
        self._rng = random.Random(seed)
        self._np_rng = np.random.default_rng(seed)
        self._tickers: list[str] = []
        self._prices: dict[str, float] = {}
        self._session_open: dict[str, float] = {}   # prev_close baseline
        self._specs: dict[str, SeedSpec] = {}
        self._cholesky: np.ndarray | None = None

    # -- membership -------------------------------------------------------
    def add(self, ticker: str) -> SeedSpec:
        ticker = ticker.upper()
        if ticker in self._prices:
            return self._specs[ticker]
        spec = spec_for(ticker)
        self._tickers.append(ticker)
        self._specs[ticker] = spec
        self._prices[ticker] = spec.price
        self._session_open[ticker] = spec.price
        self._rebuild_cholesky()
        return spec

    def remove(self, ticker: str) -> None:
        ticker = ticker.upper()
        if ticker not in self._prices:
            return
        self._tickers.remove(ticker)
        self._specs.pop(ticker, None)
        self._prices.pop(ticker, None)
        self._session_open.pop(ticker, None)
        self._rebuild_cholesky()

    def price(self, ticker: str) -> float | None:
        return self._prices.get(ticker.upper())

    def session_open(self, ticker: str) -> float | None:
        return self._session_open.get(ticker.upper())

    # -- stepping ---------------------------------------------------------
    def step(self) -> dict[str, tuple[float, float]]:
        """Advance one tick. Returns {ticker: (prev_price, new_price)}."""
        n = len(self._tickers)
        if n == 0:
            return {}

        z_indep = self._np_rng.standard_normal(n)
        z = self._cholesky @ z_indep if self._cholesky is not None else z_indep

        out: dict[str, tuple[float, float]] = {}
        for i, ticker in enumerate(self._tickers):
            spec = self._specs[ticker]
            prev = self._prices[ticker]

            drift = (spec.mu - 0.5 * spec.sigma**2) * DT_YEARS
            diffusion = spec.sigma * math.sqrt(DT_YEARS) * z[i]
            new_price = prev * math.exp(drift + diffusion)

            if self._rng.random() < EVENT_PROBABILITY_PER_TICK:
                shock = self._rng.uniform(EVENT_MIN_PCT, EVENT_MAX_PCT) * self._rng.choice([-1, 1])
                new_price *= (1 + shock)

            new_price = max(round(new_price, 4), 0.01)  # GBM floor guard
            self._prices[ticker] = new_price
            out[ticker] = (prev, new_price)
        return out

    # -- correlation ------------------------------------------------------
    def _rebuild_cholesky(self) -> None:
        n = len(self._tickers)
        if n <= 1:
            self._cholesky = None
            return
        corr = np.eye(n)
        for i in range(n):
            for j in range(i + 1, n):
                rho = correlation(self._tickers[i], self._tickers[j])
                corr[i, j] = corr[j, i] = rho
        # A hand-built matrix can be non-PSD for odd combinations; fall back to
        # the identity (independent moves) rather than crash the loop.
        try:
            self._cholesky = np.linalg.cholesky(corr)
        except np.linalg.LinAlgError:
            self._cholesky = None
```

### 5.6 The provider wrapper

`SimulatorProvider` adapts `GBMSimulator` to the `MarketDataProvider` interface: it owns the asyncio loop and writes `Quote`s into the shared cache.

```python
# backend/app/market_data/simulator.py (continued)

class SimulatorProvider(MarketDataProvider):
    def __init__(self, cache: PriceCache, seed: int | None = None) -> None:
        self._cache = cache
        self._sim = GBMSimulator(seed=seed)
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
        existing = self._cache.get(ticker)
        if existing and ticker in self._sim._prices:
            return existing                       # idempotent
        spec = self._sim.add(ticker)              # synthesizes if unknown (§4.1)
        quote = Quote.build(
            ticker, price=spec.price, prev_price=spec.price, prev_close=spec.price
        )
        await self._cache.set(quote)
        return quote

    def unwatch(self, ticker: str) -> None:
        self._sim.remove(ticker)
        self._cache.remove(ticker)

    def get_quote(self, ticker: str) -> Quote | None:
        return self._cache.get(ticker)

    def tracked_tickers(self) -> set[str]:
        return set(self._sim._tickers)

    async def _run_loop(self) -> None:
        while True:
            await asyncio.sleep(TICK_SECONDS)
            ts = now_iso()
            for ticker, (prev, new) in self._sim.step().items():
                quote = Quote.build(
                    ticker,
                    price=new,
                    prev_price=prev,
                    prev_close=self._sim.session_open(ticker),
                    timestamp=ts,
                )
                await self._cache.set(quote)
```

---

## 6. Massive Provider (Optional, Real Data)

### 6.1 Interface fit

`MassiveProvider` implements the same `start/stop/watch/unwatch/get_quote/tracked_tickers` surface. Instead of a GBM loop it runs a **polling task** that batches every tracked ticker into **one** `get_snapshot_all` call per interval — the single-call batch is what keeps the free tier (5 req/min) within limits (`MASSIVE_API.md` "How FinAlly Uses the API").

### 6.2 The `massive` client and blocking-call offload

The official `massive` client (`pip/uv add massive`, formerly `polygon-api-client`) is **synchronous**. We never call it directly on the event loop; every call is offloaded with `asyncio.to_thread(...)` so the loop stays responsive while a poll is in flight.

- Auth: `RESTClient(api_key=...)`, which sends `Authorization: Bearer <key>` automatically.
- Base URL: `https://api.massive.com` (legacy `https://api.polygon.io` still works) — handled by the client; we never hard-code it.
- Timestamps: Unix **milliseconds** (`last_trade.timestamp`) → convert with `iso_from_epoch_ms` (§2.1).

### 6.3 Poll interval

Per `PLAN.md` §6, the interval scales with tier. Configurable via `MASSIVE_POLL_SECONDS`, default `15` — free-tier safe (5 calls/min ⇒ one call every 12 s minimum; 15 s leaves margin). Paid tiers can drop to 2–5 s.

### 6.4 Field extraction

From each snapshot returned by `get_snapshot_all` (`MASSIVE_API.md` §1):

| Quote field | Massive source |
|---|---|
| `price` | `snap.last_trade.price` |
| `prev_close` | `snap.day.previous_close` |
| `prev_price` | last cached `price` for this ticker (tick-over-tick, for the flash) |
| `timestamp` | `iso_from_epoch_ms(snap.last_trade.timestamp)` |

`change_abs` / `change_pct` are then derived by `Quote.build` against `prev_close`, matching Massive's own `day.change_percent`.

### 6.5 Implementation

```python
# backend/app/market_data/massive.py
from __future__ import annotations

import asyncio
import logging
import os

from massive import RESTClient
from massive.rest.models import SnapshotMarketType

from .base import MarketDataProvider, Quote, UnknownTickerError, iso_from_epoch_ms, now_iso
from .cache import PriceCache

log = logging.getLogger("finally.market_data.massive")

DEFAULT_POLL_SECONDS = float(os.getenv("MASSIVE_POLL_SECONDS", "15"))


class MassiveProvider(MarketDataProvider):
    def __init__(
        self,
        api_key: str,
        cache: PriceCache,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
    ) -> None:
        self._api_key = api_key
        self._cache = cache
        self._poll_seconds = poll_seconds
        self._tickers: set[str] = set()
        self._last_price: dict[str, float] = {}   # for tick-over-tick prev_price
        self._client: RESTClient | None = None
        self._task: asyncio.Task | None = None
        self._degraded = False

    @property
    def degraded(self) -> bool:
        return self._degraded

    async def start(self) -> None:
        self._client = RESTClient(api_key=self._api_key)
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        # RESTClient holds an HTTP connection pool; close it off the loop.
        if self._client is not None:
            await asyncio.to_thread(self._close_client)

    def _close_client(self) -> None:
        close = getattr(self._client, "close", None)
        if callable(close):
            close()

    async def watch(self, ticker: str) -> Quote:
        ticker = ticker.upper()
        if ticker in self._tickers:
            cached = self._cache.get(ticker)
            if cached:
                return cached
        # Synchronously resolve one snapshot so callers never see a gap and an
        # invalid symbol is rejected up front (§4.4).
        quote = await self._fetch_one(ticker)
        self._tickers.add(ticker)
        self._last_price[ticker] = quote.price
        await self._cache.set(quote)
        return quote

    def unwatch(self, ticker: str) -> None:
        ticker = ticker.upper()
        self._tickers.discard(ticker)
        self._last_price.pop(ticker, None)
        self._cache.remove(ticker)

    def get_quote(self, ticker: str) -> Quote | None:
        return self._cache.get(ticker)

    def tracked_tickers(self) -> set[str]:
        return set(self._tickers)

    # -- Massive calls (all offloaded to a worker thread) -----------------
    async def _fetch_one(self, ticker: str) -> Quote:
        """One-symbol snapshot for the synchronous `watch()` path. A symbol that
        Massive cannot resolve yields UnknownTickerError -> 422."""
        try:
            snap = await asyncio.to_thread(
                self._client.get_snapshot_ticker,
                market_type=SnapshotMarketType.STOCKS,
                ticker=ticker,
            )
        except Exception as exc:  # noqa: BLE001 — see the note below
            # 404 / no results => invalid symbol. Auth/rate/5xx also land here on
            # the first fetch; treat all as "can't resolve now" so the add fails
            # cleanly rather than half-adding an unpriced ticker.
            log.warning("massive: fetch_one(%s) failed: %s", ticker, exc)
            raise UnknownTickerError(ticker) from exc

        price = _extract_price(snap)
        if price is None:
            raise UnknownTickerError(ticker)
        prev_close = _extract_prev_close(snap, fallback=price)
        ts = _extract_timestamp(snap)
        return Quote.build(ticker, price=price, prev_price=price, prev_close=prev_close, timestamp=ts)

    async def _run_loop(self) -> None:
        while True:
            await asyncio.sleep(self._poll_seconds)
            if not self._tickers:
                continue
            try:
                await self._poll_batch()
                self._degraded = False
            except Exception as exc:  # noqa: BLE001 — never let the loop die
                # Rate limit / network / parse failure: keep serving last-known
                # prices (§4.2) and mark degraded. Retry next interval.
                log.warning("massive: poll failed, serving stale prices: %s", exc)
                self._degraded = True

    async def _poll_batch(self) -> None:
        symbols = sorted(self._tickers)
        snapshots = await asyncio.to_thread(
            self._client.get_snapshot_all,
            market_type=SnapshotMarketType.STOCKS,
            tickers=symbols,
        )
        seen: set[str] = set()
        for snap in snapshots:
            ticker = str(snap.ticker).upper()
            if ticker not in self._tickers:
                continue
            price = _extract_price(snap)
            if price is None:
                continue
            seen.add(ticker)
            prev_price = self._last_price.get(ticker, price)
            prev_close = _extract_prev_close(snap, fallback=prev_price)
            ts = _extract_timestamp(snap)
            self._last_price[ticker] = price
            await self._cache.set(
                Quote.build(ticker, price=price, prev_price=prev_price,
                            prev_close=prev_close, timestamp=ts)
            )

        # Symbols Massive dropped this pass (rate-limited / momentarily bad) keep
        # their last cached Quote — no stale flat tick is emitted (§4.2).
        missing = self._tickers - seen
        if missing:
            log.info("massive: %d symbols missing this poll: %s", len(missing), sorted(missing))
            self._degraded = True


# -- tolerant field readers ----------------------------------------------
# The client's model attribute names have shifted across versions; read
# defensively so a minor client bump doesn't break the poller.

def _extract_price(snap) -> float | None:
    lt = getattr(snap, "last_trade", None)
    if lt is not None and getattr(lt, "price", None) is not None:
        return float(lt.price)
    day = getattr(snap, "day", None)
    if day is not None and getattr(day, "close", None):
        return float(day.close)
    return None


def _extract_prev_close(snap, fallback: float) -> float:
    day = getattr(snap, "day", None)
    if day is not None:
        pc = getattr(day, "previous_close", None)
        if pc:
            return float(pc)
    return fallback


def _extract_timestamp(snap) -> str:
    lt = getattr(snap, "last_trade", None)
    ms = getattr(lt, "timestamp", None) if lt is not None else None
    return iso_from_epoch_ms(int(ms)) if ms else now_iso()
```

> **Note on the broad `except`.** The `massive` client raises assorted exception types (per `MASSIVE_API.md`: 401 invalid key, 403 plan, 429 rate limit, 5xx server) and the exact classes vary by client version. In `_fetch_one` we intentionally collapse all failures to `UnknownTickerError` so a failed add never half-registers an unpriced ticker; in `_run_loop` we catch broadly so a single bad poll never kills the background task. Both paths log. If a future hard requirement needs to distinguish "invalid symbol" from "rate limited" at add-time, the place to branch on the concrete exception class is `_fetch_one`.

---

## 7. API Endpoints

### 7.1 `GET /api/watchlist` / `POST` / `DELETE` — first-paint snapshot & mutations

```python
# backend/app/api/watchlist.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db import (
    add_watchlist_ticker,
    has_open_position,
    list_watchlist_tickers,
    remove_watchlist_ticker,
)
from app.market_data import UnknownTickerError, get_cache, get_provider

router = APIRouter(prefix="/api/watchlist")


class TickerBody(BaseModel):
    ticker: str


@router.get("")
async def get_watchlist():
    """Synchronous cache read for FIRST PAINT ONLY. The frontend must not poll
    this on an interval — EventSource is the source of truth after mount (§4.3).
    A ticker with no cached quote yet (rare race at startup) returns nulls so
    the row still renders."""
    cache = get_cache()
    out = []
    for t in list_watchlist_tickers("default"):
        q = cache.get(t)
        out.append(q.to_dict() if q else {
            "ticker": t, "price": None, "prev_price": None, "prev_close": None,
            "change_abs": None, "change_pct": None, "direction": "flat",
            "timestamp": None,
        })
    return out


@router.post("")
async def add_ticker(body: TickerBody):
    ticker = body.ticker.upper().strip()
    if not ticker:
        raise HTTPException(422, detail="Ticker is required")
    provider = get_provider()
    try:
        quote = await provider.watch(ticker)   # synchronous resolve (§4.4)
    except UnknownTickerError:
        raise HTTPException(422, detail=f"Unknown ticker: {ticker}")
    add_watchlist_ticker("default", ticker)    # idempotent (UNIQUE constraint)
    return quote.to_dict()


@router.delete("/{ticker}")
async def remove_ticker(ticker: str):
    ticker = ticker.upper()
    remove_watchlist_ticker("default", ticker)
    # Keep streaming a ticker the user still holds — P&L needs its live price
    # even after it leaves the watchlist.
    if not has_open_position("default", ticker):
        get_provider().unwatch(ticker)
    return {"ok": True}
```

`has_open_position` belongs to the portfolio module but is called out here because it governs provider lifecycle: **never unwatch a ticker with an open position.**

### 7.2 `GET /api/stream/prices` — SSE

```python
# backend/app/api/streaming.py
import json

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from app.market_data import get_cache

router = APIRouter(prefix="/api/stream")

# Bounds how quickly the loop notices a client disconnect between ticks.
SSE_WAIT_TIMEOUT = 1.0


@router.get("/prices")
async def stream_prices(request: Request):
    cache = get_cache()

    async def event_generator():
        # 1. Immediate full snapshot so a fresh tab renders without waiting a
        #    tick — and so a reconnecting EventSource resyncs completely.
        for quote in cache.all().values():
            yield {"event": "price", "data": json.dumps(quote.to_dict())}

        # 2. Then push only when the cache actually changes.
        version = cache.version
        while True:
            if await request.is_disconnected():
                break
            new_version = await cache.wait_for_update(version, timeout=SSE_WAIT_TIMEOUT)
            if new_version == version:
                continue  # woke on timeout, nothing changed — loop to re-check disconnect
            version = new_version
            # Watchlists are small (tens of tickers); re-emitting the full set
            # each change is cheap and keeps the client trivially consistent.
            for quote in cache.all().values():
                yield {"event": "price", "data": json.dumps(quote.to_dict())}

    return EventSourceResponse(event_generator())
```

Frontend consumption (`PLAN.md` §10):

```ts
const es = new EventSource("/api/stream/prices");
es.addEventListener("price", (e) => {
  const q = JSON.parse(e.data);
  applyPriceUpdate(q);   // q.direction -> flash color; q.change_pct -> % column;
                         // append q.price to the sparkline buffer for q.ticker
});
```

`EventSource` reconnects natively; on reconnect the generator re-sends the full snapshot first, so the client always resyncs correctly — satisfying the "SSE resilience" E2E scenario in `PLAN.md` §12.

### 7.3 `GET /api/health`

```python
# backend/app/api/system.py
from fastapi import APIRouter

from app.market_data import get_provider

router = APIRouter(prefix="/api")


@router.get("/health")
async def health():
    provider = get_provider()
    return {
        "status": "ok",
        "market_data_status": "degraded" if provider.degraded else "ok",
    }
```

The frontend's connection-status dot (`PLAN.md` §2) can reflect `market_data_status`: `ok` → green, `degraded` → yellow, `EventSource` closed → red.

---

## 8. Worked End-to-End Flows

### 8.1 First launch (simulator, default)

1. Startup: `get_provider()` sees no `MASSIVE_API_KEY` → `SimulatorProvider`. `start()` spawns the GBM loop. `lifespan` calls `watch()` for the 10 seeded tickers → each gets a first `Quote` (`price == prev_price == prev_close`, `direction == flat`) in the cache.
2. Browser loads `/`; frontend calls `GET /api/watchlist` → 10 quotes render immediately (first paint).
3. Frontend opens `EventSource("/api/stream/prices")` → gets the full snapshot, then a `price` event stream every ~500 ms. Rows flash on `direction`, sparklines accumulate from `price`.

### 8.2 User adds an unknown ticker "ZZZZ" (simulator)

1. `POST /api/watchlist {"ticker":"ZZZZ"}` → `provider.watch("ZZZZ")`.
2. Not in `KNOWN_SEEDS` → `synthesize_seed("ZZZZ")` gives a deterministic spec; `GBMSimulator.add` rebuilds Cholesky; a first `Quote` is cached and returned (200).
3. DB row inserted; the open SSE stream picks up ZZZZ on its next tick.

### 8.3 AI chat orders "buy 5 NFLX" but NFLX isn't watched (Massive mode)

1. Trade handler: `provider.get_quote("NFLX")` → `None`.
2. Handler calls `await provider.watch("NFLX")` → `_fetch_one` does a one-symbol snapshot.
   - Valid → fresh `Quote`; fill 5 shares at `quote.price`; snapshot the portfolio.
   - Invalid symbol → `UnknownTickerError`; handler returns a `422`-shaped error the chat surfaces ("I couldn't find NFLX"). **No fill on a `None` price** (§4.4).

### 8.4 Massive rate-limit hit mid-session

1. `_poll_batch` raises (429) → caught in `_run_loop`; `degraded = True`; no cache writes this pass.
2. Cache keeps serving last-known quotes; SSE clients keep the last values (no fake flat ticks). `/api/health` reports `degraded`; the status dot goes yellow.
3. Next interval succeeds → `degraded = False`; fresh quotes resume. **No simulator data was ever mixed in** (§4.2).

---

## 9. Testing Strategy (`backend/tests/market_data/`)

Per `PLAN.md` §12. Tests use a `seed=` for determinism and `respx`/a fake `RESTClient` to avoid live network calls.

- **`test_gbm.py`** (pure engine)
  - `add()` sets `price == session_open == spec.price`; unknown ticker uses `synthesize_seed`, which is stable across two calls.
  - Over N `step()`s all prices stay `> 0` and within a sane multiple of the seed (no blowup) for reasonable sigma.
  - Same-group tickers show positive sign-agreement over many steps (correlation sanity); identity fallback triggers on a non-PSD matrix without raising.
- **`test_simulator_provider.py`**
  - `watch()` returns a `Quote` synchronously with `direction == flat` on the first call; a second `watch()` is idempotent (returns the cached quote, no duplicate sim state).
  - After ticks, `get_quote()` reflects the latest cached price; `unwatch()` → `get_quote()` is `None` and the ticker leaves `tracked_tickers()`.
- **`test_cache.py`**
  - `set()` then `get()` round-trips; `version` increments; `all()` returns a copy.
  - `wait_for_update()` returns promptly after a `set()` from another task, and via timeout when nothing changes.
- **`test_massive.py`** (fake `RESTClient` / `respx`)
  - `_fetch_one` raises `UnknownTickerError` when the client raises or returns no price.
  - `_poll_batch` updates the cache for returned symbols, leaves omitted symbols frozen (last quote intact), and sets `degraded = True` when any tracked symbol is missing.
  - A raised error in `_run_loop` sets `degraded = True` and does **not** kill the loop (next iteration still runs).
  - Field extraction: ms timestamp → ISO; `prev_close` from `day.previous_close`; `prev_price` = last cached price.
- **`test_interface_conformance.py`** — parametrized over `[SimulatorProvider, MassiveProvider(fake client)]`, asserting both satisfy the contract: `watch` before `get_quote` is non-`None`; `unwatch` then `get_quote` is `None`; `tracked_tickers()` tracks `watch`/`unwatch`; `degraded` is a bool.

---

## 10. Summary of Decisions

| Question (REVIEW_code.md / REVIEW.md) | Decision |
|---|---|
| Unknown ticker in simulator | `synthesize_seed()` — deterministic seed on first `watch()`; never reject (§4.1) |
| Massive per-ticker fetch failure | Freeze last cached price; set `degraded`; don't crash the loop (§4.2) |
| Massive can't resolve a symbol at all | `UnknownTickerError` → `422` on `POST /api/watchlist`; never added (§4.2) |
| Never mix simulator prices into Massive mode | Confirmed — no cross-provider fallback, only a degraded flag (§4.2) |
| REST vs SSE source of truth | REST = first-paint snapshot only; SSE authoritative after mount (§4.3) |
| Trade fill with no cached price | Handler `await provider.watch(ticker)` before fill; only fails on real `UnknownTickerError` (§4.4) |
| Daily change % vs. per-tick flash | `Quote` carries `prev_close` (day change) **and** `prev_price` (flash direction) (§4.5) |
| Held-but-unwatched ticker | Never `unwatch` a ticker with an open position — P&L needs its price (§7.1) |

---

## 11. Reconciliation With the Sketch Docs

This document is the authoritative contract; the three sketches remain useful background but are **superseded** where they differ:

| Topic | Sketch | This document (authoritative) |
|---|---|---|
| Module path | `app/market/` (`MARKET_INTERFACE.md`, `MARKET_SIMULATOR.md`) | `app/market_data/` (§1) |
| Data shape | `PriceUpdate` (`ticker, price, previous_price, change, direction, timestamp`) | `Quote` — adds `prev_close`, `change_pct`, split of flash vs day change (§2.1) |
| Interface name / shape | `MarketDataSource` (`start(tickers)`, async `add_ticker`/`remove_ticker`, no return) | `MarketDataProvider` — `watch()` returns a `Quote` and resolves synchronously; adds `get_quote`, `degraded` (§2.2) |
| Cache lock | `threading.Lock` (`MARKET_INTERFACE.md`) | `asyncio.Condition` + version counter, so SSE wakes on change instead of polling (§3) |
| Simulator correlation | Cholesky (`MARKET_SIMULATOR.md`) vs. beta-blend (old design draft) | Cholesky, wrapped in `GBMSimulator` + `SimulatorProvider` (§5.2, §5.5–5.6) |
| Massive access | Placeholder `httpx` calls to a fictional `/quote` endpoint (old draft) | Real `massive` `RESTClient.get_snapshot_all` / `get_snapshot_ticker`, offloaded via `asyncio.to_thread` (§6), per `MASSIVE_API.md` |
| Seed prices | Two different tables across sketches | Single `KNOWN_SEEDS` (price + mu + sigma + group) in `seeds.py` (§5.4) |

Everything above the `_fetch_one` / `_poll_batch` seam (cache, SSE, interface, simulator) is agnostic to the exact Massive response shape — that is the whole point of the shared interface, and the only place to touch if the real client's model attributes shift is the tolerant readers in §6.5.
