"""Watchlist REST routes."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.services import watchlist as svc

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


class TickerRequest(BaseModel):
    ticker: str


@router.get("")
def get_watchlist() -> list[dict]:
    return svc.get_watchlist()


@router.post("")
async def add(req: TickerRequest) -> dict:
    await svc.add_ticker(req.ticker)
    return {"status": "ok"}


@router.delete("/{ticker}")
async def remove(ticker: str) -> dict:
    await svc.remove_ticker(ticker)
    return {"status": "ok"}
