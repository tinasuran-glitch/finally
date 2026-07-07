# Review: Changes Since Last Commit

Base reviewed: `HEAD`
Scope reviewed: tracked edits plus untracked files reported by `git ls-files --others --exclude-standard`.

## Findings

### High - reviewer agents are tied to one local checkout

`.claude/agents/change-reviewer.md:9`  
`.claude/agents/codex-reviewer.md:6`

Both reviewer agent definitions invoke Codex with `-C '/Users/tinahua/Desktop/vibe coding /finally'`. These files are project-level agent definitions, so committing this path makes them non-portable: another clone, another username, or a renamed directory will either fail or review/write results in the wrong checkout if that absolute path happens to exist. Use the current working directory/repository context instead of a machine-specific absolute path.

### Medium - generated review artifact contains stale guidance

`planning/REVIEW_code.md:5`

The untracked review artifact still carries a resolved "Critical" secret finding and its summary says to "Fix the exposed secret first", even though the current `planning/PLAN.md` contains only the placeholder `OPENROUTER_API_KEY=your-openrouter-api-key-here`. If committed, this will leave future agents with contradictory instructions and may trigger unnecessary incident-response work. Regenerate the artifact from the current state, remove the stale summary, or leave it out of the commit if it is scratch output.

### Low - README points to `.env.example`, but that file is absent

`README.md:49`

The README tells users to see `.env.example`, and `planning/PLAN.md` also describes `.env.example` as committed, but the working tree does not contain that file. Until the scaffold exists, this is a broken documentation reference. Either add a minimal `.env.example` alongside the README change or soften the README wording so it does not point at a missing file.

## Open Questions

- Should `planning/REVIEW_code.md` be committed as a durable review artifact, or is it temporary output from the Codex reviewer command?
- Should `.claude/agents/codex-reviewer.md` be a shared project agent? If so, it needs the same portability fix as `change-reviewer`.

## Summary

The README expansion and the new `planning/PLAN.md` clarification notes are consistent with the planning-stage project. The main issues are around committing machine-specific automation and stale generated review output.

---

# Review: Commit 05d5fb7 — Market Data Backend Design

**Date:** 2026-07-07 00:54:45  
**Commit:** `05d5fb7f53466699d97e4acb3f07e6263e18cac8`  
**Title:** Add detailed market data backend design doc  
**Files Changed:** `planning/MARKET_DATA_DESIGN.md` (+747 lines)

## Overview

This commit delivers a comprehensive implementation specification for the market data subsystem, resolving all open questions raised in `REVIEW_code.md` and providing concrete code examples for both the simulator (default) and Massive API (real data) providers. The document bridges from the high-level `PLAN.md` architecture to actionable backend code.

## What Was Accomplished

### 1. Unified Interface Design ✅
- **`Quote` dataclass** (lines 62–91): Frozen, hashable, minimal shape with `ticker`, `price`, `prev_price`, `change_abs`, `change_pct`, `direction`, `timestamp`. All providers conform to this shape.
- **`MarketDataProvider` ABC** (lines 98–151): Async-first lifecycle (`start/stop/watch/unwatch/get_quote/tracked_tickers`) that guarantees initial quotes on watch and clean error handling via `UnknownTickerError`.
- **Factory pattern** (lines 156–188): Singleton `get_provider()` that selects `SimulatorProvider` or `MassiveProvider` based on `MASSIVE_API_KEY` env var, with `get_cache()` singleton for shared state.

### 2. Shared Price Cache ✅
- **`PriceCache` class** (lines 223–267): In-memory dict guarded by `asyncio.Lock` + `asyncio.Condition`.
- **Async-safe update notification** (lines 251–266): `wait_for_update()` blocks efficiently on `_condition`, enabling SSE to wake on every tick without polling.
- **No cross-process concerns**: Appropriate for single-process app + SQLite.

### 3. Simulator Provider (Default) ✅
- **GBM model** (lines 295–310): Geometric Brownian motion with sector correlation via blended `Z = beta * Z_sector + sqrt(1 - beta²) * Z_idio`.
- **Known seeds** (lines 313–344): AAPL, GOOGL, MSFT, etc., with realistic parameters (mu=0.05-0.15, sigma=0.18-0.55) and sector grouping (tech, auto, finance, streaming).
- **Deterministic unknown ticker synthesis** (lines 348–359): `synthesize_seed(ticker)` derives stable price/vol/group from SHA-256 hash of ticker name, enabling "add any ticker" UX without rejections.
- **Event shocks** (lines 341–343): ~0.3% probability per 500ms tick of ±2–5% price move, preventing flat markets.
- **Full implementation** (lines 364–456): Async loop managing multi-ticker GBM evolution, sector shock generation, price caching, and event injection.

### 4. Massive Provider (Real Data) ✅
- **REST polling architecture** (lines 464–468): Batches watched tickers into one request per `MASSIVE_POLL_SECONDS` (default 15s, safe for free tier).
- **Failure handling** (lines 280–282, 555–593):
  - Per-ticker price freeze on partial failures (ticker omitted from batch response).
  - Global `degraded` flag on hard HTTP errors (network/parse failure).
  - Loop continues after error; no silent fallback to simulator.
- **Unknown ticker rejection** (lines 547–549): `_fetch_one()` raises `UnknownTickerError` on 404, which becomes `422 Unprocessable Entity` at the API boundary.
- **Placeholder API contract** (line 595 note): URL and request/response shape awaiting real Massive/Polygon.io docs, but interface is API-agnostic.

### 5. Open Questions Resolution ✅

All four medium-level findings from `REVIEW_code.md` are resolved:

| Question | Resolution |
|----------|-----------|
| Unknown ticker handling | Lazily synthesize deterministic seed on first `watch()` for SimulatorProvider; reject with 422 for MassiveProvider. Never mix simulators into "real" mode. |
| Massive per-ticker failure | Freeze last cached price for missing ticker in batch; only set `degraded` flag on hard errors. No automatic fallback. |
| REST vs SSE source of truth | `GET /api/watchlist` = first-paint snapshot (synchronous cache read); SSE = authoritative stream. Frontend must not poll REST after mount. Explicitly stated in §7.1 & frontend notes. |
| Trade fill price availability | Trade handler calls `await provider.watch(ticker)` synchronously if quote is `None`, ensuring every trade has a fresh price or raises `UnknownTickerError` (→ 422). No `None` fills. |

### 6. API Endpoint Contracts ✅
- **`GET /api/watchlist`** (lines 602–627): Synchronous read, first-paint only. Includes `None` prices for tickers not yet cached.
- **`POST /api/watchlist`** (lines 629–639): Adds ticker, calls `provider.watch()`, catches `UnknownTickerError` → 422.
- **`DELETE /api/watchlist/{ticker}`** (lines 641–649): Removes ticker, guards against unwatching held positions.
- **`GET /api/stream/prices`** (lines 668–690): SSE event source, sends full snapshot on connection + after every cache version change.
- **`GET /api/health`** (lines 707–712): Reports `market_data_status: "ok" | "degraded"`.

### 7. Testing Strategy ✅
- **`test_simulator.py`**: Idempotency, deterministic unknown seed, price bounds, sector correlation.
- **`test_cache.py`**: Round-trip, async notification, timeout.
- **`test_massive.py`**: Unknown ticker → exception, partial batch omission, degraded flag, loop resilience (mocked transport).
- **`test_interface_conformance.py`**: Parametrized over both providers, verify watch/get/unwatch lifecycle.

## Structural Strengths

1. **Clear separation of concerns**: Cache is independent of providers; providers depend only on cache interface, not each other.
2. **Concrete code examples**: All major classes have full, copy-paste-ready implementations. No pseudocode or hand-wavy sections.
3. **Environment-driven polymorphism**: Provider selection via `MASSIVE_API_KEY` env var is simple and testable; no runtime branching logic in the backend.
4. **Async-first design**: All I/O is async; no blocking in the main thread; SSE can be efficient.
5. **Explicit error handling**: `UnknownTickerError` is a named exception, not a string message; propagates cleanly to API status codes.
6. **Deterministic fallback**: Unknown tickers don't fail in simulator mode; they produce stable, repeatable prices for the same ticker name within a session.

## Completeness

- ✅ Directory layout and module structure defined.
- ✅ Every class has full code.
- ✅ Factory pattern and lifecycle hooks (`start()`, `stop()` at app boot/shutdown).
- ✅ Decisions table (§9) closes all gaps from REVIEW_code.md.
- ✅ Testing strategy (§8) is concrete and implementable.
- ✅ SSE resilience (auto-reconnect + full snapshot replay) is addressed.

## Issues & Recommendations

### No Critical Issues

All major architectural decisions are sound and well-justified.

### Medium - API placeholder pending real Massive/Polygon.io contract

**Line 595, `massive.py`**: The `MASSIVE_BASE_URL`, request shape (`/quotes?symbols=...`), and response format (`{ "results": [ { symbol, price, prev_close }, ... ] }`) are placeholders. Once the real Massive API docs are available, update lines 483–593 (only `_fetch_one` / `_poll_batch`); the rest of the system is agnostic to the exact shape.

**Mitigation:** This is acceptable for a design doc; add a note in the implementation task to validate against live API docs before finalizing.

### Low - Fractional-share precision in `Quote.build()`

**Lines 84–87**: Prices and changes are rounded to 4 decimal places (`round(..., 4)`). This is reasonable for cents/basis points but should match frontend and database constraints. If the app requires different precision (e.g., 2 for USD), update consistently across Quote, frontend, and trade validation.

**Mitigation:** Add a comment or a config constant `PRICE_DECIMAL_PLACES = 4`.

### Low - Seed data is subjective

**Lines 328–339**: The known seed prices and volatilities (e.g., TSLA sigma=0.55 "auto" group) are reasonable but not calibrated to real market data. For a production app, backfill with historical IV and correlation matrices. For a prototype/learning app, the current values are fine.

**Mitigation:** No action needed for implementation; document in a follow-up "calibration" task.

## Code Quality

- **Style**: Consistent with Python 3.10+ (dataclass, type hints, f-strings, `|` union syntax).
- **Async best practices**: `asyncio.Lock` + `Condition`, proper task cancellation, resource cleanup in `stop()`.
- **No synthetic concerns**: The code is straightforward; no unnecessary abstraction layers.

## Readability & Navigation

- Clear section headings and subsections.
- Code snippets are labeled with file paths.
- Inline comments explain non-obvious logic (e.g., beta blending in line 441).
- A decisions table (§9) provides a quick reference back to REVIEW_code.md.

## Alignment with PLAN.md

The design doc faithfully implements the market data architecture from PLAN.md §6–8:
- ✅ Unified interface (PLAN.md §6: "single SDK").
- ✅ Simulator with sector correlation (PLAN.md §6: "tech stocks move together").
- ✅ Massive fallback when `MASSIVE_API_KEY` is set (PLAN.md §7).
- ✅ SSE for real-time prices (PLAN.md §10: "EventSource on port 3000").
- ✅ Trade fills at current price (PLAN.md §8: "execute at the quoted price").

## Ready for Implementation

This document is implementation-ready. A backend team can:
1. Clone the directory structure (§1).
2. Copy-paste the code from §§2–6.
3. Integrate with FastAPI routes (§7) and SQLite watchlist logic.
4. Write tests following §8 strategy.
5. Swap Massive API URL/shape once real docs are available (§6.3 note).

## Summary

The commit successfully closes the gap between high-level architecture (PLAN.md) and implementable code. All four open questions from REVIEW_code.md are resolved with clear reasoning and concrete examples. The design is solid, async-first, and ready for a backend team to execute. The only pending item is validation against the real Massive/Polygon.io API contract once available.
