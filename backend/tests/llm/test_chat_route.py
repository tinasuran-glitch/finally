"""Route-level tests for POST /api/chat using the deterministic mock."""


def test_chat_buy_executes_trade(client):
    r = client.post("/api/chat", json={"message": "buy 5 AAPL"})
    assert r.status_code == 200
    body = r.json()
    assert len(body["trades"]) == 1
    assert body["trades"][0]["ticker"] == "AAPL"
    assert body["trades"][0]["status"] == "executed"
    assert body["errors"] == []


def test_chat_failed_trade_does_not_crash(client):
    r = client.post("/api/chat", json={"message": "buy 100000 AAPL"})
    assert r.status_code == 200
    body = r.json()
    assert body["trades"] == []
    assert len(body["errors"]) == 1
    assert "Insufficient cash" in body["errors"][0]
    assert "Note:" in body["message"]


def test_chat_unknown_ticker_reported(client):
    r = client.post("/api/chat", json={"message": "buy 1 ZZZ"})
    assert r.status_code == 200
    body = r.json()
    assert body["trades"] == []
    assert len(body["errors"]) == 1


def test_chat_watchlist_add(client):
    r = client.post("/api/chat", json={"message": "add PYPL to watchlist"})
    assert r.status_code == 200
    body = r.json()
    assert body["watchlist_changes"][0]["ticker"] == "PYPL"
    assert body["watchlist_changes"][0]["action"] == "add"


def test_chat_generic_message_no_actions(client):
    r = client.post("/api/chat", json={"message": "how is my portfolio?"})
    assert r.status_code == 200
    body = r.json()
    assert body["trades"] == []
    assert body["watchlist_changes"] == []
    assert body["message"]


def test_chat_persists_history(client):
    client.post("/api/chat", json={"message": "buy 5 AAPL"})
    from app.db import repository as repo

    msgs = repo.list_chat_messages(limit=10)
    roles = [m["role"] for m in msgs]
    assert "user" in roles and "assistant" in roles
    assistant = [m for m in msgs if m["role"] == "assistant"][-1]
    assert assistant["actions"]["trades"][0]["ticker"] == "AAPL"
