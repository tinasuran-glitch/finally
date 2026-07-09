"""Fixtures giving each test an isolated temp SQLite database."""

import pytest

from app.db import connection


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Point FINALLY_DB_PATH at a fresh temp file and reset the init guard."""
    path = tmp_path / "finally.db"
    monkeypatch.setenv("FINALLY_DB_PATH", str(path))
    connection._initialized.clear()
    yield path
    connection._initialized.clear()
