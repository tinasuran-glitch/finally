# Market Data Backend — Detailed Design

## 0. Purpose & Scope

This document is the implementation contract for the market data subsystem described in `PLAN.md` sections 6, 7, and 8. It defines:

- The unified `MarketDataProvider` interface both implementations conform to
- The in-memory `PriceCache` shared by all providers and consumed by SSE, REST, and the portfolio module
- The **Simulator** provider (GBM-based, default)
- The **Massive** provider (REST polling, optional, used when `MASSIVE_API_KEY` is set)
- The SSE streaming endpoint and the price-related REST endpoints
- Centralized configuration for every tunable
- Resolutions to the open questions raised in `REVIEW_code.md` (unknown tickers, Massive fallback, REST-vs-SSE source of truth, trade-fill price availability)

Scope: `backend/app/market_data/` and the price-related parts of `backend/app/api/`. Portfolio/trade math is out of scope except for the **price-availability contract** the portfolio module depends on (§8).

### 0.1 Data-flow at a glance

```
                 ┌───────────────────────────┐
                 │  Active MarketDataProvider │
                 │  (Simulator OR Massive)    │  ← chosen once by env var
                 └──────────────┬────────────┘
                     writes Quotes (only writer)
                                │
                                ▼
                 ┌───────────────────────────┐
                 │        PriceCache          │  in-memory, single source of truth
                 │  {ticker -> (ver, Quote)}  │
                 └───┬───────────┬────────────┘
        snapshot /   │           │  wait_for_update / changes_since
        get_price    │           │
             ┌───────▼──┐   ┌────▼─────────┐   ┌──────────────────┐
             │ REST API │   │  SSE stream  │   │ Portfolio module │
             │ (1st     │   │ (authoritative│   │ (valuation, P&L, │
             │  paint)  │   │  live feed)  │   │  snapshots)      │
             └──────────┘   └──────────────┘   └──────────────────┘
```

The provider is the **only writer**. Everything else reads. This is what lets us swap Simulator ↔ Massive without touching a single consumer.

---

## 1. Directory Layout

```
backend/
└── app/
    ├── config.py                 # Settings (pydantic-settings): all tunables + env
    └── market_data/
        ├── __init__.py           # factory get_provider(), get_cache(); re-exports
        ├── base.py               # MarketDataProvider ABC, Quote, Direction, errors
        ├── cache.py              # PriceCache (async-safe, versioned)
        ├── simulator.py          # SimulatorProvider (correlated GBM)
        ├── massive.py            # MassiveProvider (batched REST polling)
        └── seeds.py              # Known seed specs, correlation groups, synth seeds
```

`app/api/*` and `app/portfolio/*` depend only on `market_data/__init__.py` (factory + cache) and `market_data/base.py` (types) — never on `simulator.py` / `massive.py` directly.

---

## 2. Configuration

All tunables live in one place so behavior is env-driven and tests can override cleanly.

```python
# backend/app/config.py
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Provider selection ---
    massive_api_key: str = ""                 # empty -> simulator

    # --- Streaming cadence ---
    tick_seconds: float = 0.5                 # simulator tick / SSE emit cadence
    sse_disconnect_check_seconds: float = 2.0 # how often the SSE loop re-checks liveness
    sse_ping_seconds: int = 15                # keep-alive comment interval (proxies)

    # --- Simulator dynamics ---
    # Each 500ms wall-clock tick represents this many SECONDS of market time.
    # Real market time at 500ms would move prices imperceptibly (see §5.1),
    # so we accelerate: ~240s (4 market-minutes) per tick gives lively but
    # non-cartoonish motion (~0.1-0.2% per tick at typical sigma).
    sim_market_seconds_per_tick: float = 240.0
    sim_correlation_beta: float = 0.6         # how strongly a ticker tracks its sector
    sim_event_prob_per_tick: float = 0.003    # chance of a shock event per ticker/tick
    sim_event_min_pct: float = 0.02
    sim_event_max_pct: float = 0.05
    sim_seed: int | None = None               # set in tests for determinism

    # --- Massive polling ---
    massive_base_url: str = "https://api.massive.dev/v1"  # placeholder; see §6
    massive_poll_seconds: int = 15            # free tier (5 req/min) safe default
    massive_http_timeout: float = 10.0

    @property
    def use_massive(self) -> bool:
        return bool(self.massive_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

> **Trading-year constant.** GBM needs a market-seconds-per-year figure to annualize σ/μ. Regular US sessions are 6.5h × 252 days: `SECONDS_PER_TRADING_YEAR = 252 * 6.5 * 3600 = 5,896,800`. Defined in `seeds.py` and used by the simulator (§5).

---

## 3. The Unified Interface

### 3.1 `Quote` — the shared data shape

Every provider produces this exact shape. It is cached, streamed over SSE, and returned by REST.

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
    """A single price observation for one ticker. Immutable."""
    ticker: str
    price: float
    prev_price: float
    change_abs: float
    change_pct: float
    direction: Direction
    timestamp: str  # ISO-8601 UTC millis, e.g. "2026-07-07T14:32:01.123Z"

    @staticmethod
    def build(ticker: str, price: float, prev_price: float, timestamp: str) -> "Quote":
        change_abs = price - prev_price
        if change_abs > 1e-9:
            direction = Direction.UP
        elif change_abs < -1e-9:
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

    def to_dict(self) -> dict:
        """
        Wire format for SSE and REST. NOTE: `Quote` uses slots=True, so it has
        no __dict__ — never do json.dumps(quote.__dict__). Use this instead.
        Also flattens the Direction enum to its string value for JSON.
        """
        return {
            "ticker": self.ticker,
            "price": self.price,
            "prev_price": self.prev_price,
            "change_abs": self.change_abs,
            "change_pct": self.change_pct,
            "direction": self.direction.value,
            "timestamp": self.timestamp,
        }
```

### 3.2 Ticker normalization

One canonical form everywhere (cache keys, DB rows, API params) prevents `aapl`/`AAPL` desync.

```python
# backend/app/market_data/base.py (continued)
import re

_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")  # 1-10 chars, letter-led


class InvalidTickerError(ValueError):
    """Ticker string is malformed (fails format validation)."""


class UnknownTickerError(Exception):
    """Provider cannot resolve an otherwise well-formed symbol (e.g. Massive 404)."""
    def __init__(self, ticker: str):
        self.ticker = ticker
        super().__init__(f"Unknown ticker: {ticker}")


def normalize_ticker(raw: str) -> str:
    """Uppercase + trim, then validate shape. Raises InvalidTickerError on garbage."""
    t = (raw or "").strip().upper()
    if not _TICKER_RE.match(t):
        raise InvalidTickerError(f"Invalid ticker: {raw!r}")
    return t
```

`InvalidTickerError` (bad shape, e.g. `"$$$"`) and `UnknownTickerError` (well-formed but unresolvable, e.g. Massive returns 404) are distinct so the API can map them to `422` with different messages.

### 3.3 `MarketDataProvider` — the abstract interface

```python
# backend/app/market_data/base.py (continued)

class MarketDataProvider(abc.ABC):
    """
    Common interface for any market data source.

    Lifecycle:
      1. start()                 once at app startup — spawns the background task
      2. watch() / watch_many()  as the watchlist grows (batched at startup)
      3. get_quote()             synchronous reads by REST + trade endpoint
      4. unwatch()               as the watchlist shrinks
      5. stop()                  once at shutdown — cancels task, closes clients

    Contract: implementations MUST write every price update into the injected
    PriceCache and MUST NOT keep a second copy of "current price" that consumers
    read from — the cache is the single source of truth so get_quote() and the
    SSE stream can never disagree. (Providers may keep internal simulation state
    such as the running GBM price; that is not a consumer-visible quote.)
    """

    @abc.abstractmethod
    async def start(self) -> None: ...

    @abc.abstractmethod
    async def stop(self) -> None: ...

    @abc.abstractmethod
    async def watch(self, ticker: str) -> Quote:
        """
        Track `ticker`; synchronously produce and cache an initial Quote before
        returning, so a watched ticker is never quote-less. Idempotent.
        `ticker` is assumed already normalized. Raises UnknownTickerError if the
        source cannot resolve it (Massive only).
        """

    async def watch_many(self, tickers: list[str]) -> dict[str, Quote]:
        """
        Batch variant used at startup. Default = sequential watch(); providers
        with a batch API (Massive) override this to avoid N calls / rate limits.
        Unresolvable tickers are skipped and omitted from the result (they are
        never silently dropped from the DB by this layer — the caller decides).
        """
        out: dict[str, Quote] = {}
        for t in tickers:
            try:
                out[t] = await self.watch(t)
            except UnknownTickerError:
                continue
        return out

    @abc.abstractmethod
    def unwatch(self, ticker: str) -> None:
        """Stop tracking. Idempotent."""

    @abc.abstractmethod
    def get_quote(self, ticker: str) -> Quote | None:
        """Last cached Quote or None if not tracked. Never blocks."""

    def get_price(self, ticker: str) -> float | None:
        """Convenience for the portfolio module: latest price or None."""
        q = self.get_quote(ticker)
        return q.price if q else None

    @abc.abstractmethod
    def tracked_tickers(self) -> set[str]: ...

    @property
    def degraded(self) -> bool:
        """True when the source is not delivering fresh data (Massive only)."""
        return False
```

### 3.4 Factory — environment-driven selection

```python
# backend/app/market_data/__init__.py
from app.config import get_settings
from .base import (
    MarketDataProvider, Quote, Direction,
    UnknownTickerError, InvalidTickerError, normalize_ticker,
)
from .cache import PriceCache
from .simulator import SimulatorProvider
from .massive import MassiveProvider

_provider: MarketDataProvider | None = None
_cache = PriceCache()


def get_cache() -> PriceCache:
    return _cache


def get_provider() -> MarketDataProvider:
    """Singleton. Source is decided once, at first access, from settings."""
    global _provider
    if _provider is None:
        s = get_settings()
        _provider = (
            MassiveProvider(cache=_cache, settings=s)
            if s.use_massive
            else SimulatorProvider(cache=_cache, settings=s)
        )
    return _provider


def reset_provider_for_tests() -> None:
    """Test hook: drop the singletons so a fresh provider/cache is built."""
    global _provider, _cache
    _provider = None
    _cache = PriceCache()


__all__ = [
    "MarketDataProvider", "Quote", "Direction",
    "UnknownTickerError", "InvalidTickerError", "normalize_ticker",
    "PriceCache", "get_cache", "get_provider", "reset_provider_for_tests",
]
```

FastAPI wiring — note the **batched** startup watch:

```python
# backend/app/main.py (excerpt)
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.market_data import get_provider
from app.db import list_watchlist_tickers, list_position_tickers

@asynccontextmanager
async def lifespan(app: FastAPI):
    provider = get_provider()
    await provider.start()
    # Track everything the user needs priced: watchlist ∪ held positions.
    tickers = sorted(set(list_watchlist_tickers("default")) |
                     set(list_position_tickers("default")))
    await provider.watch_many(tickers)   # one batch call for Massive
    yield
    await provider.stop()

app = FastAPI(lifespan=lifespan)
```

---

## 4. The Shared Price Cache

Single-process asyncio app, so we do not need thread locks — we need cooperative-scheduling safety and an efficient wake mechanism for SSE. The cache is **versioned**: a global monotonic counter plus a per-ticker stamp, so an SSE connection can ask "what changed since version V?" and get only the deltas instead of the whole book on every tick.

```python
# backend/app/market_data/cache.py
import asyncio
from .base import Quote


class PriceCache:
    """
    In-memory latest-quote store; the one source of truth read by SSE, REST,
    and portfolio valuation. Ephemeral — rebuilt from provider seeds each start.
    """

    def __init__(self) -> None:
        self._quotes: dict[str, Quote] = {}
        self._ticker_version: dict[str, int] = {}   # ticker -> version at last set
        self._version = 0                            # global monotonic counter
        self._cond = asyncio.Condition()             # binds to the running loop lazily

    async def set(self, quote: Quote) -> None:
        async with self._cond:
            self._version += 1
            self._quotes[quote.ticker] = quote
            self._ticker_version[quote.ticker] = self._version
            self._cond.notify_all()

    # --- synchronous reads (safe: no await between dict ops on one loop) ---
    def get(self, ticker: str) -> Quote | None:
        return self._quotes.get(ticker)

    def snapshot(self) -> list[Quote]:
        return list(self._quotes.values())

    @property
    def version(self) -> int:
        return self._version

    def changes_since(self, since_version: int) -> tuple[list[Quote], int]:
        """Quotes whose last update is newer than `since_version`, + current version."""
        changed = [
            q for t, q in self._quotes.items()
            if self._ticker_version.get(t, 0) > since_version
        ]
        return changed, self._version

    def remove(self, ticker: str) -> None:
        self._quotes.pop(ticker, None)
        self._ticker_version.pop(ticker, None)

    async def wait_for_update(self, since_version: int, timeout: float) -> int:
        """
        Block until `_version` advances past `since_version` or `timeout` elapses;
        return the current version. Lets the SSE loop sleep until a real tick
        rather than busy-polling.
        """
        async with self._cond:
            try:
                await asyncio.wait_for(
                    self._cond.wait_for(lambda: self._version > since_version),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                pass
            return self._version
```

Why versioning matters: at ~500ms ticks a single provider pass calls `set()` once per ticker, bumping the global version by N. An SSE client that last saw version `V` calls `changes_since(V)` and receives exactly the quotes touched since — no redundant re-broadcast of unchanged tickers, and no missed updates.

---

## 5. Simulator Provider (Default)

### 5.1 Model — and why time is accelerated

Each ticker follows **geometric Brownian motion**:

```
S(t+Δt) = S(t) · exp( (μ − σ²/2)·Δt + σ·√Δt · Z ),   Z ~ N(0,1)
```

with μ, σ **annualized**. The subtle, easy-to-get-wrong part is Δt. If we used *real* elapsed time, a 500ms tick is `Δt = 0.5 / 5,896,800 ≈ 8.5e-8` years, giving a per-tick move std of `σ·√Δt ≈ 0.30 · 2.9e-4 ≈ 0.009%`. The terminal would look **frozen** — killing the price-flash and sparkline UX the plan calls for.

So the simulator runs on **accelerated market time**: each 500ms wall-clock tick advances `SIM_MARKET_SECONDS_PER_TICK` (default 240s ≈ 4 market-minutes) of simulated market time:

```
Δt_years = sim_market_seconds_per_tick / SECONDS_PER_TRADING_YEAR
         = 240 / 5,896,800 ≈ 4.07e-5
per-tick std at σ=0.30:  0.30 · √4.07e-5 ≈ 0.0019  → ~0.19% typical move
```

Lively, visibly streaming, still statistically GBM. This one constant is the single knob for "how fast does the market feel."

**Correlated sector moves** (PLAN.md §6 "tech stocks move together"): each tick draws one shared shock `Z_sector` per correlation group, blended with a per-ticker idiosyncratic shock:

```
Z_ticker = β·Z_sector + √(1−β²)·Z_idio      (β default 0.6)
```

### 5.2 Seed data

```python
# backend/app/market_data/seeds.py
import hashlib
from dataclasses import dataclass

SECONDS_PER_TRADING_YEAR = 252 * 6.5 * 3600  # 5,896,800


@dataclass(frozen=True)
class SeedSpec:
    price: float
    mu: float       # annualized drift
    sigma: float    # annualized volatility
    group: str      # correlation group key


SECTOR_GROUPS = ["tech", "auto", "finance", "streaming", "misc"]

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


def synthesize_seed(ticker: str) -> SeedSpec:
    """
    Deterministic, plausible seed for a ticker the simulator doesn't know.
    Same ticker -> same seed within and across process starts, so re-adding a
    removed ticker resumes from a stable base. Assigned to the 'misc' group so
    ad-hoc tickers don't distort a real sector's correlation.
    """
    h = int(hashlib.sha256(ticker.encode()).hexdigest(), 16)
    price = 20.0 + (h % 48000) / 100.0         # $20.00 – $500.00
    mu = 0.04 + ((h >> 16) % 100) / 1000.0      # 0.040 – 0.139
    sigma = 0.20 + ((h >> 32) % 300) / 1000.0   # 0.200 – 0.499
    return SeedSpec(round(price, 2), mu, sigma, "misc")
```

### 5.3 Implementation

```python
# backend/app/market_data/simulator.py
import asyncio
import math
import random
from datetime import datetime, timezone

from app.config import Settings
from .base import MarketDataProvider, Quote
from .cache import PriceCache
from .seeds import (
    KNOWN_SEEDS, SeedSpec, synthesize_seed, SECONDS_PER_TRADING_YEAR,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class SimulatorProvider(MarketDataProvider):
    def __init__(self, cache: PriceCache, settings: Settings) -> None:
        self._cache = cache
        self._s = settings
        self._specs: dict[str, SeedSpec] = {}
        self._prices: dict[str, float] = {}          # internal running price
        self._rng = random.Random(settings.sim_seed)
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
        existing = self._cache.get(ticker)
        if ticker in self._specs and existing:
            return existing                          # idempotent
        spec = KNOWN_SEEDS.get(ticker) or synthesize_seed(ticker)
        self._specs[ticker] = spec
        self._prices[ticker] = spec.price
        quote = Quote.build(ticker, spec.price, spec.price, _now_iso())
        await self._cache.set(quote)
        return quote

    def unwatch(self, ticker: str) -> None:
        self._specs.pop(ticker, None)
        self._prices.pop(ticker, None)
        self._cache.remove(ticker)

    def get_quote(self, ticker: str) -> Quote | None:
        return self._cache.get(ticker)

    def tracked_tickers(self) -> set[str]:
        return set(self._specs)

    async def _run_loop(self) -> None:
        dt = self._s.sim_market_seconds_per_tick / SECONDS_PER_TRADING_YEAR
        sqrt_dt = math.sqrt(dt)
        beta = self._s.sim_correlation_beta
        idio_scale = math.sqrt(1 - beta * beta)
        while True:
            await asyncio.sleep(self._s.tick_seconds)
            if not self._specs:
                continue

            # one shared shock per active correlation group this tick
            groups = {s.group for s in self._specs.values()}
            group_shock = {g: self._rng.gauss(0, 1) for g in groups}

            for ticker, spec in list(self._specs.items()):
                prev = self._prices[ticker]
                z = beta * group_shock[spec.group] + idio_scale * self._rng.gauss(0, 1)
                drift = (spec.mu - 0.5 * spec.sigma ** 2) * dt
                diffusion = spec.sigma * sqrt_dt * z
                new_price = prev * math.exp(drift + diffusion)

                # occasional dramatic event
                if self._rng.random() < self._s.sim_event_prob_per_tick:
                    pct = self._rng.uniform(self._s.sim_event_min_pct, self._s.sim_event_max_pct)
                    new_price *= (1 + pct) if self._rng.random() < 0.5 else (1 - pct)

                new_price = max(new_price, 0.01)      # price floor
                self._prices[ticker] = new_price
                await self._cache.set(Quote.build(ticker, new_price, prev, _now_iso()))
```

The `list(self._specs.items())` snapshot makes the loop safe against a concurrent `watch()`/`unwatch()` mutating the dict during the `await self._cache.set(...)` inside the loop body.

---

## 6. Massive Provider (Optional, Real Data)

### 6.1 Shape

Same `watch/unwatch/get_quote/tracked_tickers` surface; instead of an internal GBM loop it runs a poller that **batches all tracked tickers into one REST call per interval**. It overrides `watch_many` so startup priming is a single request, not N.

### 6.2 Poll interval

`massive_poll_seconds` (default 15). Free tier is 5 req/min → one batched call every ≥12s is safe; 15s leaves margin. Paid tiers can lower it.

### 6.3 Failure semantics (resolves REVIEW_code.md Q)

| Situation | Behavior |
|---|---|
| First-ever `watch()` returns 404 | raise `UnknownTickerError` → API `422`, ticker never added |
| Whole poll fails (network/5xx/parse) | keep last-known quotes; set `degraded=True`; retry next interval |
| Ticker omitted from an otherwise-OK batch (rate-limited/transient) | freeze that ticker's last quote; mark `degraded=True`; no fake tick emitted |
| Recovery | first clean, complete poll clears `degraded` |

We **never** substitute simulator prices in Massive mode — mixing synthetic data into a "real data" feed would be misleading for a finance app. Degradation is surfaced honestly via `/api/health`.

### 6.4 Implementation

```python
# backend/app/market_data/massive.py
import asyncio
from datetime import datetime, timezone

import httpx

from app.config import Settings
from .base import MarketDataProvider, Quote, UnknownTickerError
from .cache import PriceCache


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class MassiveProvider(MarketDataProvider):
    def __init__(self, cache: PriceCache, settings: Settings) -> None:
        self._cache = cache
        self._s = settings
        self._tickers: set[str] = set()
        self._prev: dict[str, float] = {}            # last price, for change calc
        self._client: httpx.AsyncClient | None = None
        self._task: asyncio.Task | None = None
        self._degraded = False

    @property
    def degraded(self) -> bool:
        return self._degraded

    async def start(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=self._s.massive_base_url,
            headers={"Authorization": f"Bearer {self._s.massive_api_key}"},
            timeout=self._s.massive_http_timeout,
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
        if ticker in self._tickers:
            cached = self._cache.get(ticker)
            if cached:
                return cached
        quote = await self._fetch_one(ticker)        # may raise UnknownTickerError
        self._tickers.add(ticker)
        self._prev[ticker] = quote.price
        await self._cache.set(quote)
        return quote

    async def watch_many(self, tickers: list[str]) -> dict[str, Quote]:
        """Prime everything in ONE batch call so startup doesn't spend N requests."""
        wanted = [t for t in tickers if t]
        if not wanted:
            return {}
        self._tickers.update(wanted)                 # provisional; unresolved get pruned
        got = await self._poll_batch(prime=True)
        unresolved = set(wanted) - set(got)
        for t in unresolved:                         # symbol invalid/unavailable at prime
            self._tickers.discard(t)
        return got

    def unwatch(self, ticker: str) -> None:
        self._tickers.discard(ticker)
        self._prev.pop(ticker, None)
        self._cache.remove(ticker)

    def get_quote(self, ticker: str) -> Quote | None:
        return self._cache.get(ticker)

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
            await asyncio.sleep(self._s.massive_poll_seconds)
            if not self._tickers:
                continue
            try:
                got = await self._poll_batch()
                # degraded if the batch itself failed (handled below) OR it
                # came back missing tickers we asked for.
                self._degraded = len(got) < len(self._tickers)
            except (httpx.HTTPError, KeyError, ValueError):
                # Whole-poll failure: keep last-known quotes, do not crash.
                self._degraded = True

    async def _poll_batch(self, prime: bool = False) -> dict[str, Quote]:
        """
        Fetch every tracked ticker in one call, update the cache, and RETURN the
        quotes that resolved. Returning the result (rather than mutating a
        degraded flag here) keeps failure bookkeeping in exactly one place —
        the caller — so it can't be clobbered.
        """
        symbols = ",".join(sorted(self._tickers))
        resp = await self._client.get("/quotes", params={"symbols": symbols})
        resp.raise_for_status()
        payload = resp.json()   # {"results": [{"symbol","price","prev_close"}, ...]}

        resolved: dict[str, Quote] = {}
        for row in payload.get("results", []):
            ticker = str(row["symbol"]).upper()
            if ticker not in self._tickers:
                continue
            price = float(row["price"])
            prev = self._prev.get(ticker, float(row.get("prev_close", price)))
            quote = Quote.build(ticker, price, prev, _now_iso())
            self._prev[ticker] = price
            await self._cache.set(quote)
            resolved[ticker] = quote
        return resolved
```

> **Endpoint contract is a placeholder.** `massive_base_url` and the request/response shapes above are stand-ins pending the real Massive/Polygon.io reference. `_fetch_one` and `_poll_batch` are the **only** two methods that touch the wire format — everything else (cache, SSE, interface, failure policy) is source-agnostic by design.

---

## 7. API Endpoints

### 7.1 Request/response models

```python
# backend/app/api/schemas.py
from pydantic import BaseModel


class AddTickerRequest(BaseModel):
    ticker: str            # validated/normalized in the handler


class QuoteOut(BaseModel):
    ticker: str
    price: float | None
    prev_price: float | None
    change_abs: float | None
    change_pct: float | None
    direction: str
    timestamp: str | None
```

### 7.2 Watchlist — REST is first-paint only (resolves REVIEW_code.md Q)

`GET /api/watchlist` is a **synchronous cache read** whose sole job is to give the page numbers before the `EventSource` handshake completes. The frontend must not poll it; SSE is authoritative after mount.

```python
# backend/app/api/watchlist.py
from fastapi import APIRouter, HTTPException
from app.market_data import (
    get_provider, get_cache, normalize_ticker,
    UnknownTickerError, InvalidTickerError,
)
from app.db import (
    add_watchlist_ticker, remove_watchlist_ticker,
    list_watchlist_tickers, has_open_position,
)
from .schemas import AddTickerRequest, QuoteOut

router = APIRouter(prefix="/api/watchlist")


@router.get("", response_model=list[QuoteOut])
async def get_watchlist():
    cache = get_cache()
    out = []
    for t in list_watchlist_tickers("default"):
        q = cache.get(t)
        out.append(q.to_dict() if q else {
            "ticker": t, "price": None, "prev_price": None,
            "change_abs": None, "change_pct": None,
            "direction": "flat", "timestamp": None,
        })
    return out


@router.post("", response_model=QuoteOut)
async def add_ticker(body: AddTickerRequest):
    try:
        ticker = normalize_ticker(body.ticker)
    except InvalidTickerError as e:
        raise HTTPException(422, detail=str(e))
    try:
        quote = await get_provider().watch(ticker)    # blocks until first quote
    except UnknownTickerError:
        raise HTTPException(422, detail=f"Unknown ticker: {ticker}")
    add_watchlist_ticker("default", ticker)            # persist only after success
    return quote.to_dict()


@router.delete("/{ticker}")
async def remove_ticker(ticker: str):
    try:
        ticker = normalize_ticker(ticker)
    except InvalidTickerError as e:
        raise HTTPException(422, detail=str(e))
    remove_watchlist_ticker("default", ticker)
    # Keep pricing a ticker we still hold shares in (needed for P&L), even if
    # it's off the watchlist.
    if not has_open_position("default", ticker):
        get_provider().unwatch(ticker)
    return {"ok": True}
```

### 7.3 SSE — `GET /api/stream/prices`

Sends a full snapshot on connect (so a fresh/reconnecting tab renders immediately), then streams **only deltas** via `changes_since`. `sse-starlette`'s `ping` emits keep-alive comments so proxies don't cut idle connections.

```python
# backend/app/api/streaming.py
import json
from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse
from app.config import get_settings
from app.market_data import get_cache

router = APIRouter(prefix="/api/stream")


@router.get("/prices")
async def stream_prices(request: Request):
    cache = get_cache()
    s = get_settings()

    async def event_generator():
        # 1) initial snapshot — and adopt the current version so we don't
        #    immediately re-send the same quotes as a phantom "delta".
        version = cache.version
        for q in cache.snapshot():
            yield {"event": "price", "data": json.dumps(q.to_dict())}

        # 2) deltas only
        while True:
            if await request.is_disconnected():
                break
            version = await cache.wait_for_update(version, timeout=s.sse_disconnect_check_seconds)
            changed, version = cache.changes_since(version)
            for q in changed:
                yield {"event": "price", "data": json.dumps(q.to_dict())}

    # ping= keeps the connection warm through proxies during quiet spells.
    return EventSourceResponse(event_generator(), ping=s.sse_ping_seconds)
```

Frontend (PLAN.md §10) — `EventSource` reconnects natively; on reconnect the generator re-sends the snapshot, so the client always resyncs (satisfies the "SSE resilience" E2E scenario):

```ts
const es = new EventSource("/api/stream/prices");
es.addEventListener("price", (e) => {
  const q = JSON.parse(e.data);
  applyPriceUpdate(q);   // flash green/red, append to sparkline buffer
});
```

### 7.4 Health — `GET /api/health`

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
        "tracked": len(provider.tracked_tickers()),
    }
```

---

## 8. Consumer Contract: Portfolio & Trades

The portfolio module is a **reader** of the cache; it never writes prices. Two touch-points matter to this design:

### 8.1 Trade fill — synchronous-watch-then-fill (resolves REVIEW_code.md Q)

A trade must fill at a real current price. If the ticker isn't tracked yet (e.g. the AI orders a symbol not on the watchlist), the trade handler tracks it first, then reads the fresh price. A trade never fills on a `None` price; it only fails for a genuinely unresolvable symbol.

```python
# backend/app/portfolio/trades.py (price-availability portion)
from fastapi import HTTPException
from app.market_data import (
    get_provider, normalize_ticker, UnknownTickerError, InvalidTickerError,
)

async def resolve_fill_price(raw_ticker: str) -> tuple[str, float]:
    try:
        ticker = normalize_ticker(raw_ticker)
    except InvalidTickerError as e:
        raise HTTPException(422, detail=str(e))

    provider = get_provider()
    price = provider.get_price(ticker)
    if price is None:                    # not tracked yet — track & get first quote
        try:
            quote = await provider.watch(ticker)
        except UnknownTickerError:
            raise HTTPException(422, detail=f"Unknown ticker: {ticker}")
        price = quote.price
    return ticker, price
```

Downstream, the existing trade logic validates cash/shares and records the trade; a filled trade should also ensure the ticker stays tracked (so P&L keeps updating) — which `watch()` already guarantees.

### 8.2 Valuation & snapshots

- **Position valuation / total portfolio value** read `provider.get_price(ticker)` (or `get_cache().get`) for every held ticker. Because startup primes `watchlist ∪ positions` (§3.4) and `remove_ticker` won't unwatch a held ticker (§7.2), a held position always has a live price.
- **`portfolio_snapshots`** (PLAN.md §7): a background task records total value every 30s and immediately after each trade. It reads current prices from the cache — no separate market-data path.

---

## 9. Concurrency & Correctness Notes

- **Single event loop, no threads.** Synchronous cache reads (`get`, `snapshot`, `changes_since`) are safe because no `await` occurs between dict operations. Only `set()` / `wait_for_update()` use the `Condition`, because they coordinate the SSE wake.
- **Mutation during iteration.** Both provider loops iterate a `list(...)` snapshot of their tracked set, so a concurrent `watch`/`unwatch` during an inner `await` can't raise "dict changed size during iteration."
- **`degraded` bookkeeping lives in exactly one place** (`_run_loop`), fed by `_poll_batch`'s return value — it cannot be set-then-clobbered within a single poll.
- **Lazy loop binding.** `PriceCache` is constructed at import time (before a running loop exists). `asyncio.Condition()` binds to the loop on first `await`, which is always inside a request/task — safe on Python 3.10+.

---

## 10. Testing Strategy (`backend/tests/market_data/`)

Per PLAN.md §12. Use `reset_provider_for_tests()` between cases; set `sim_seed` for determinism.

- **`test_quote.py`** — `Quote.build` sets `direction`/`change_pct` correctly (incl. `prev_price==0`); `to_dict()` is JSON-serializable and emits `direction` as a string (guards the slots/`__dict__` regression).
- **`test_ticker.py`** — `normalize_ticker` uppercases/trims valid input; raises `InvalidTickerError` on `""`, `"$$$"`, over-long, or digit-led symbols.
- **`test_cache.py`** — `set`→`get` round-trips; `changes_since(v)` returns only newer quotes and the right version; `wait_for_update` wakes promptly on a concurrent `set` and returns via timeout when idle.
- **`test_simulator.py`** — first `watch()` returns a Quote with `price==prev_price`; repeat `watch()` is idempotent; `synthesize_seed(x)` is stable across calls; over N ticks prices stay `>0` and within a sane band; same-group tickers show positive sign-correlation; per-tick move magnitude matches the accelerated-Δt expectation (guards against the "frozen prices" regression).
- **`test_massive.py`** (`respx`/`httpx.MockTransport`) — `_fetch_one` raises `UnknownTickerError` on 404; a whole-poll `HTTPError` sets `degraded` without crashing `_run_loop`; a batch missing a ticker freezes it and sets `degraded`; a later complete poll clears `degraded`; `watch_many` issues **one** request and prunes unresolved symbols.
- **`test_interface_conformance.py`** — parametrized over both providers: `watch`→`get_quote` non-`None`; `unwatch`→`get_quote` `None`; `tracked_tickers()` tracks watch/unwatch; `get_price` mirrors `get_quote().price`.

---

## 11. Summary of Decisions

| Question (REVIEW_code.md) | Decision |
|---|---|
| Unknown ticker in simulator | `synthesize_seed()` — deterministic seed, `misc` group; never rejected |
| Massive per-ticker fetch failure | Freeze last cached quote; mark `degraded`; poll loop survives |
| Massive symbol unresolvable at first watch | `UnknownTickerError` → `422`; ticker never persisted |
| Malformed ticker string | `InvalidTickerError` → `422` (distinct from "unknown") |
| Simulator vs Massive data mixing | Never mixed; degradation surfaced via `/api/health` only |
| REST vs SSE source of truth | REST = first-paint snapshot; SSE (deltas) authoritative after mount |
| Trade fill with no cached price | `watch()` synchronously, then fill; fails only on genuine `UnknownTickerError` |
| Held-but-unwatchlisted ticker | Stays tracked so P&L keeps updating (`remove_ticker` checks `has_open_position`) |
| Prices visibly moving at 500ms | Accelerated market time (`sim_market_seconds_per_tick`) — real annualized σ would look frozen |
| Massive startup rate limits | `watch_many` primes all tickers in one batched request |
