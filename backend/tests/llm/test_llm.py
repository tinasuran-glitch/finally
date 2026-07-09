"""Unit tests for the LLM service: structured parsing and mock determinism."""

import pytest

from app.services import llm


def test_parse_valid_full_response():
    payload = (
        '{"message": "Done.", '
        '"trades": [{"ticker": "AAPL", "side": "buy", "quantity": 5}], '
        '"watchlist_changes": [{"ticker": "PYPL", "action": "add"}]}'
    )
    parsed = llm.ChatResponse.model_validate_json(payload)
    assert parsed.message == "Done."
    assert parsed.trades[0].ticker == "AAPL"
    assert parsed.watchlist_changes[0].action == "add"


def test_parse_message_only_defaults_empty():
    parsed = llm.ChatResponse.model_validate_json('{"message": "Hi"}')
    assert parsed.trades == []
    assert parsed.watchlist_changes == []


def test_parse_malformed_raises():
    with pytest.raises(Exception):
        llm.ChatResponse.model_validate_json("not json")


def test_mock_buy_pattern(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "true")
    portfolio = {"total_value": 10000.0, "cash_balance": 10000.0, "positions": []}
    r = llm.generate_response("please buy 5 AAPL now", portfolio, [], [])
    assert len(r.trades) == 1
    assert r.trades[0].ticker == "AAPL"
    assert r.trades[0].side == "buy"
    assert r.trades[0].quantity == 5.0


def test_mock_sell_and_watchlist(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "true")
    portfolio = {"total_value": 10000.0, "cash_balance": 10000.0, "positions": []}
    r = llm.generate_response("sell 2 TSLA and add PYPL to watchlist", portfolio, [], [])
    assert r.trades[0].side == "sell"
    assert r.trades[0].ticker == "TSLA"
    assert r.watchlist_changes[0].ticker == "PYPL"
    assert r.watchlist_changes[0].action == "add"


def test_mock_deterministic(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "true")
    portfolio = {"total_value": 10000.0, "cash_balance": 10000.0, "positions": []}
    a = llm.generate_response("buy 3 NVDA", portfolio, [], [])
    b = llm.generate_response("buy 3 NVDA", portfolio, [], [])
    assert a.model_dump() == b.model_dump()


def test_mock_no_pattern_returns_summary(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "true")
    portfolio = {"total_value": 12345.0, "cash_balance": 5000.0, "positions": []}
    r = llm.generate_response("how am I doing?", portfolio, [], [])
    assert r.trades == []
    assert r.watchlist_changes == []
    assert "12345" in r.message
