"""Portfolio valuation and trade execution — shared by REST routes and chat."""

from __future__ import annotations

from typing import Literal

from app import state
from app.db import repository as repo


def get_portfolio() -> dict:
    """Return cash, valued positions, and total portfolio value."""
    cash = repo.get_profile()["cash_balance"]
    positions = []
    positions_value = 0.0

    for pos in repo.list_positions():
        ticker = pos["ticker"]
        quantity = pos["quantity"]
        avg_cost = pos["avg_cost"]
        price = state.price_cache.get_price(ticker)
        current_price = price if price is not None else avg_cost
        market_value = quantity * current_price
        cost_basis = quantity * avg_cost
        unrealized_pnl = market_value - cost_basis
        pnl_percent = (unrealized_pnl / cost_basis * 100) if cost_basis else 0.0
        positions_value += market_value

        positions.append(
            {
                "ticker": ticker,
                "quantity": quantity,
                "avg_cost": avg_cost,
                "current_price": current_price,
                "market_value": round(market_value, 2),
                "unrealized_pnl": round(unrealized_pnl, 2),
                "pnl_percent": round(pnl_percent, 2),
            }
        )

    return {
        "cash_balance": round(cash, 2),
        "positions": positions,
        "total_value": round(cash + positions_value, 2),
    }


def execute_trade(
    ticker: str, side: Literal["buy", "sell"], quantity: float
) -> dict:
    """Execute a market order at the current cache price.

    Raises ValueError on unknown ticker or validation failure.
    """
    ticker = ticker.upper()
    if quantity <= 0:
        raise ValueError("Quantity must be greater than zero.")

    price = state.price_cache.get_price(ticker)
    if price is None:
        raise ValueError(f"No market price available for {ticker}.")

    cash = repo.get_profile()["cash_balance"]
    position = repo.get_position(ticker)

    if side == "buy":
        cost = quantity * price
        if cost > cash:
            raise ValueError(
                f"Insufficient cash: need ${cost:.2f}, have ${cash:.2f}."
            )
        held_qty = position["quantity"] if position else 0.0
        held_cost = position["avg_cost"] if position else 0.0
        new_qty = held_qty + quantity
        new_avg_cost = (held_qty * held_cost + quantity * price) / new_qty
        repo.update_cash_balance(cash - cost)
        repo.upsert_position(ticker, new_qty, new_avg_cost)
    elif side == "sell":
        held_qty = position["quantity"] if position else 0.0
        if quantity > held_qty:
            raise ValueError(
                f"Insufficient shares: trying to sell {quantity}, hold {held_qty}."
            )
        proceeds = quantity * price
        remaining = held_qty - quantity
        repo.update_cash_balance(cash + proceeds)
        if remaining > 0:
            repo.upsert_position(ticker, remaining, position["avg_cost"])
        else:
            repo.delete_position(ticker)
    else:
        raise ValueError(f"Invalid side: {side!r}. Must be 'buy' or 'sell'.")

    trade = repo.record_trade(ticker, side, quantity, price)
    repo.record_snapshot(get_portfolio()["total_value"])
    return trade


def get_history(limit: int = 500) -> list[dict]:
    """Return portfolio value snapshots over time."""
    return repo.list_snapshots(limit=limit)
