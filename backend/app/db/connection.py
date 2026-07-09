"""Database path resolution, connection helper, and lazy initialization."""

import os
import sqlite3
import threading
from pathlib import Path

from .schema import initialize

_initialized: set[str] = set()
_lock = threading.Lock()


def db_path() -> Path:
    """Resolve the SQLite file path from FINALLY_DB_PATH or the repo default."""
    override = os.environ.get("FINALLY_DB_PATH")
    if override:
        return Path(override)
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "db" / "finally.db"


def get_connection() -> sqlite3.Connection:
    """Return a new connection with Row factory, ensuring schema and seed exist."""
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    _ensure_initialized(conn, str(path))
    return conn


def _ensure_initialized(conn: sqlite3.Connection, key: str) -> None:
    """Initialize the database once per path within this process."""
    if key in _initialized:
        return
    with _lock:
        if key not in _initialized:
            initialize(conn)
            _initialized.add(key)
