"""FastAPI application entrypoint for FinAlly."""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

# Load the repo-root .env before any import that reads env vars at import/startup
# (OPENROUTER_API_KEY for chat, MASSIVE_API_KEY for the market data source).
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

import asyncio  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from app import state  # noqa: E402
from app.api import chat, health, portfolio, watchlist  # noqa: E402
from app.db import repository as repo  # noqa: E402
from app.market import (  # noqa: E402
    PriceCache,
    create_market_data_source,
    create_stream_router,
)
from app.services import portfolio as portfolio_svc  # noqa: E402

SNAPSHOT_INTERVAL_SECONDS = 30


async def _snapshot_loop() -> None:
    """Record a portfolio value snapshot on a fixed interval."""
    while True:
        await asyncio.sleep(SNAPSHOT_INTERVAL_SECONDS)
        repo.record_snapshot(portfolio_svc.get_portfolio()["total_value"])


@asynccontextmanager
async def lifespan(app: FastAPI):
    state.market_source = create_market_data_source(state.price_cache)
    await state.market_source.start(repo.list_watchlist())
    snapshot_task = asyncio.create_task(_snapshot_loop())
    try:
        yield
    finally:
        snapshot_task.cancel()
        await state.market_source.stop()


state.price_cache = PriceCache()

app = FastAPI(title="FinAlly", lifespan=lifespan)

# Next.js's `next dev` rewrite proxy buffers streamed responses (~128KB) before
# forwarding chunks, which breaks live SSE. So in dev the frontend connects its
# EventSource directly to this backend instead of going through the proxy —
# that needs CORS. Production is a same-origin static export (no dev server,
# no proxy), so this middleware is unused there.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
    ],
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(portfolio.router)
app.include_router(watchlist.router)
app.include_router(chat.router)
app.include_router(create_stream_router(state.price_cache))

if Path("static").is_dir():
    app.mount("/", StaticFiles(directory="static", html=True), name="static")
