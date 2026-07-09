"""Database subsystem for FinAlly.

SQLite data-access layer with lazy schema init and default seeding.
Import the connection helper or the repository functions directly:

    from app.db import get_connection
    from app.db import repository as repo
    repo.get_profile()
"""

from .connection import db_path, get_connection
from .repository import (
    add_chat_message,
    add_to_watchlist,
    delete_position,
    get_position,
    get_profile,
    list_chat_messages,
    list_positions,
    list_snapshots,
    list_trades,
    list_watchlist,
    record_snapshot,
    record_trade,
    remove_from_watchlist,
    update_cash_balance,
    upsert_position,
)

__all__ = [
    "db_path",
    "get_connection",
    "get_profile",
    "update_cash_balance",
    "list_watchlist",
    "add_to_watchlist",
    "remove_from_watchlist",
    "list_positions",
    "get_position",
    "upsert_position",
    "delete_position",
    "record_trade",
    "list_trades",
    "record_snapshot",
    "list_snapshots",
    "add_chat_message",
    "list_chat_messages",
]
