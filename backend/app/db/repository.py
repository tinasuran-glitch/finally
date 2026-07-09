"""Data-access functions for the single default user.

Each function opens its own short-lived connection (safe under FastAPI's
threaded/async request model) and returns plain JSON-serializable dicts.
"""

import json

from .connection import get_connection
from .schema import DEFAULT_USER_ID, new_id, now_iso

USER = DEFAULT_USER_ID


# --- Profile -------------------------------------------------------------

def get_profile() -> dict:
    """Return the user profile row as a dict."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM users_profile WHERE id = ?", (USER,)
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


def update_cash_balance(new_balance: float) -> None:
    """Set the user's cash balance."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE users_profile SET cash_balance = ? WHERE id = ?",
            (new_balance, USER),
        )
        conn.commit()
    finally:
        conn.close()


# --- Watchlist -----------------------------------------------------------

def list_watchlist() -> list[str]:
    """Return the user's watched tickers in insertion order."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT ticker FROM watchlist WHERE user_id = ? ORDER BY added_at",
            (USER,),
        ).fetchall()
        return [row["ticker"] for row in rows]
    finally:
        conn.close()


def add_to_watchlist(ticker: str) -> None:
    """Add a ticker to the watchlist (no-op if already present)."""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO watchlist (id, user_id, ticker, added_at) "
            "VALUES (?, ?, ?, ?)",
            (new_id(), USER, ticker, now_iso()),
        )
        conn.commit()
    finally:
        conn.close()


def remove_from_watchlist(ticker: str) -> None:
    """Remove a ticker from the watchlist (no-op if absent)."""
    conn = get_connection()
    try:
        conn.execute(
            "DELETE FROM watchlist WHERE user_id = ? AND ticker = ?",
            (USER, ticker),
        )
        conn.commit()
    finally:
        conn.close()


# --- Positions -----------------------------------------------------------

def list_positions() -> list[dict]:
    """Return all current positions as dicts."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM positions WHERE user_id = ? ORDER BY ticker",
            (USER,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_position(ticker: str) -> dict | None:
    """Return a single position by ticker, or None if not held."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM positions WHERE user_id = ? AND ticker = ?",
            (USER, ticker),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def upsert_position(ticker: str, quantity: float, avg_cost: float) -> dict:
    """Create or update a position, returning the resulting row."""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO positions (id, user_id, ticker, quantity, avg_cost, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (user_id, ticker) DO UPDATE SET "
            "quantity = excluded.quantity, avg_cost = excluded.avg_cost, "
            "updated_at = excluded.updated_at",
            (new_id(), USER, ticker, quantity, avg_cost, now_iso()),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM positions WHERE user_id = ? AND ticker = ?",
            (USER, ticker),
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


def delete_position(ticker: str) -> None:
    """Remove a position (no-op if absent)."""
    conn = get_connection()
    try:
        conn.execute(
            "DELETE FROM positions WHERE user_id = ? AND ticker = ?",
            (USER, ticker),
        )
        conn.commit()
    finally:
        conn.close()


# --- Trades --------------------------------------------------------------

def record_trade(ticker: str, side: str, quantity: float, price: float) -> dict:
    """Append a trade to the log and return the stored row."""
    conn = get_connection()
    try:
        trade_id = new_id()
        executed_at = now_iso()
        conn.execute(
            "INSERT INTO trades (id, user_id, ticker, side, quantity, price, executed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (trade_id, USER, ticker, side, quantity, price, executed_at),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM trades WHERE id = ?", (trade_id,)
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


def list_trades(limit: int = 100) -> list[dict]:
    """Return recent trades, most recent first."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM trades WHERE user_id = ? "
            "ORDER BY executed_at DESC LIMIT ?",
            (USER, limit),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


# --- Portfolio snapshots -------------------------------------------------

def record_snapshot(total_value: float) -> dict:
    """Record a portfolio value snapshot and return the stored row."""
    conn = get_connection()
    try:
        snapshot_id = new_id()
        conn.execute(
            "INSERT INTO portfolio_snapshots (id, user_id, total_value, recorded_at) "
            "VALUES (?, ?, ?, ?)",
            (snapshot_id, USER, total_value, now_iso()),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM portfolio_snapshots WHERE id = ?", (snapshot_id,)
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


def list_snapshots(limit: int = 500) -> list[dict]:
    """Return portfolio snapshots in chronological order (oldest first)."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM portfolio_snapshots WHERE user_id = ? "
            "ORDER BY recorded_at LIMIT ?",
            (USER, limit),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


# --- Chat messages -------------------------------------------------------

def add_chat_message(role: str, content: str, actions=None) -> dict:
    """Store a chat message. `actions` is serialized to JSON; returns the row."""
    conn = get_connection()
    try:
        message_id = new_id()
        actions_json = json.dumps(actions) if actions is not None else None
        conn.execute(
            "INSERT INTO chat_messages (id, user_id, role, content, actions, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (message_id, USER, role, content, actions_json, now_iso()),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM chat_messages WHERE id = ?", (message_id,)
        ).fetchone()
        return _chat_row_to_dict(row)
    finally:
        conn.close()


def list_chat_messages(limit: int = 50) -> list[dict]:
    """Return recent chat messages in chronological order (oldest first)."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM chat_messages WHERE user_id = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (USER, limit),
        ).fetchall()
        return [_chat_row_to_dict(row) for row in reversed(rows)]
    finally:
        conn.close()


def _chat_row_to_dict(row) -> dict:
    """Convert a chat_messages row to a dict, parsing the JSON actions field."""
    data = dict(row)
    data["actions"] = json.loads(data["actions"]) if data["actions"] else None
    return data
