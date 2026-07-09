"""Chat REST route: POST /api/chat.

Orchestrates the full flow: store the user message, load context, call the
LLM (or mock), auto-execute the returned trades and watchlist changes, store
the assistant reply with its actions, and return the complete result.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.db import repository as repo
from app.services import llm
from app.services.portfolio import execute_trade, get_portfolio
from app.services.watchlist import add_ticker, get_watchlist, remove_ticker

router = APIRouter(prefix="/api/chat", tags=["chat"])

HISTORY_LIMIT = 20


class ChatRequest(BaseModel):
    message: str


@router.post("")
async def chat(req: ChatRequest) -> dict:
    repo.add_chat_message("user", req.message)

    portfolio = get_portfolio()
    watchlist = get_watchlist()
    history = repo.list_chat_messages(limit=HISTORY_LIMIT)

    response = llm.generate_response(req.message, portfolio, watchlist, history)

    executed_trades: list[dict] = []
    errors: list[str] = []
    for trade in response.trades:
        try:
            result = execute_trade(trade.ticker, trade.side, trade.quantity)
            executed_trades.append(
                {
                    "ticker": result["ticker"],
                    "side": result["side"],
                    "quantity": result["quantity"],
                    "price": result["price"],
                    "status": "executed",
                }
            )
        except ValueError as exc:
            errors.append(f"{trade.side} {trade.quantity} {trade.ticker}: {exc}")

    applied_changes: list[dict] = []
    for change in response.watchlist_changes:
        try:
            if change.action == "add":
                await add_ticker(change.ticker)
            elif change.action == "remove":
                await remove_ticker(change.ticker)
            else:
                raise ValueError(f"Unknown watchlist action: {change.action!r}")
            applied_changes.append(
                {"ticker": change.ticker.upper(), "action": change.action}
            )
        except ValueError as exc:
            errors.append(f"{change.action} {change.ticker}: {exc}")

    message_text = response.message
    if errors:
        message_text += "\n\nNote: " + "; ".join(errors)

    actions = {"trades": executed_trades, "watchlist_changes": applied_changes}
    repo.add_chat_message("assistant", message_text, actions=actions)

    return {
        "message": message_text,
        "trades": executed_trades,
        "watchlist_changes": applied_changes,
        "errors": errors,
    }
