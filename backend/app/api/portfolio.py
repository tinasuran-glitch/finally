"""Portfolio REST routes."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import portfolio as svc

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


class TradeRequest(BaseModel):
    ticker: str
    quantity: float
    side: Literal["buy", "sell"]


@router.get("")
def get_portfolio() -> dict:
    return svc.get_portfolio()


@router.post("/trade")
def trade(req: TradeRequest) -> dict:
    try:
        return svc.execute_trade(req.ticker, req.side, req.quantity)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/history")
def history() -> list[dict]:
    return svc.get_history()
