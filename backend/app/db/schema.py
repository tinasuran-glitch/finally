"""SQLite schema definitions and default seed data for FinAlly."""

import uuid
from datetime import datetime, timezone

DEFAULT_USER_ID = "default"
DEFAULT_CASH_BALANCE = 10000.0
DEFAULT_WATCHLIST = [
    "AAPL", "GOOGL", "MSFT", "AMZN", "TSLA",
    "NVDA", "META", "JPM", "V", "NFLX",
]

SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS users_profile (
        id TEXT PRIMARY KEY,
        cash_balance REAL NOT NULL DEFAULT 10000.0,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS watchlist (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL DEFAULT 'default',
        ticker TEXT NOT NULL,
        added_at TEXT NOT NULL,
        UNIQUE (user_id, ticker)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS positions (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL DEFAULT 'default',
        ticker TEXT NOT NULL,
        quantity REAL NOT NULL,
        avg_cost REAL NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE (user_id, ticker)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS trades (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL DEFAULT 'default',
        ticker TEXT NOT NULL,
        side TEXT NOT NULL,
        quantity REAL NOT NULL,
        price REAL NOT NULL,
        executed_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS portfolio_snapshots (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL DEFAULT 'default',
        total_value REAL NOT NULL,
        recorded_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chat_messages (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL DEFAULT 'default',
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        actions TEXT,
        created_at TEXT NOT NULL
    )
    """,
]


def now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    """Return a fresh UUID4 string for use as a primary key."""
    return str(uuid.uuid4())


def initialize(conn) -> None:
    """Create tables if missing and seed default data. Idempotent."""
    for statement in SCHEMA_STATEMENTS:
        conn.execute(statement)
    _seed(conn)
    conn.commit()


def _seed(conn) -> None:
    """Insert the default user profile and watchlist if not already present."""
    conn.execute(
        "INSERT OR IGNORE INTO users_profile (id, cash_balance, created_at) "
        "VALUES (?, ?, ?)",
        (DEFAULT_USER_ID, DEFAULT_CASH_BALANCE, now_iso()),
    )
    for ticker in DEFAULT_WATCHLIST:
        conn.execute(
            "INSERT OR IGNORE INTO watchlist (id, user_id, ticker, added_at) "
            "VALUES (?, ?, ?, ?)",
            (new_id(), DEFAULT_USER_ID, ticker, now_iso()),
        )
