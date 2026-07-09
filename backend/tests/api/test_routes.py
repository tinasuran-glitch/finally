"""Route-level tests using FastAPI TestClient."""


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_get_portfolio_empty(client):
    r = client.get("/api/portfolio")
    assert r.status_code == 200
    body = r.json()
    assert body["cash_balance"] == 10000.0
    assert body["positions"] == []


def test_trade_buy(client):
    r = client.post(
        "/api/portfolio/trade",
        json={"ticker": "AAPL", "quantity": 5, "side": "buy"},
    )
    assert r.status_code == 200
    assert r.json()["ticker"] == "AAPL"

    body = client.get("/api/portfolio").json()
    assert body["cash_balance"] == 10000.0 - 950.0


def test_trade_insufficient_cash(client):
    r = client.post(
        "/api/portfolio/trade",
        json={"ticker": "AAPL", "quantity": 1000, "side": "buy"},
    )
    assert r.status_code == 400
    assert "Insufficient cash" in r.json()["detail"]


def test_trade_invalid_ticker(client):
    r = client.post(
        "/api/portfolio/trade",
        json={"ticker": "ZZZZ", "quantity": 1, "side": "buy"},
    )
    assert r.status_code == 400


def test_trade_invalid_side(client):
    r = client.post(
        "/api/portfolio/trade",
        json={"ticker": "AAPL", "quantity": 1, "side": "hold"},
    )
    assert r.status_code == 422


def test_history_after_trade(client):
    client.post(
        "/api/portfolio/trade",
        json={"ticker": "AAPL", "quantity": 1, "side": "buy"},
    )
    r = client.get("/api/portfolio/history")
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_get_watchlist_seeded(client):
    r = client.get("/api/watchlist")
    assert r.status_code == 200
    tickers = [e["ticker"] for e in r.json()]
    assert "AAPL" in tickers


def test_add_and_remove_watchlist(client):
    r = client.post("/api/watchlist", json={"ticker": "NVDA"})
    assert r.status_code == 200
    tickers = [e["ticker"] for e in client.get("/api/watchlist").json()]
    assert "NVDA" in tickers

    r = client.delete("/api/watchlist/NVDA")
    assert r.status_code == 200
    tickers = [e["ticker"] for e in client.get("/api/watchlist").json()]
    assert "NVDA" not in tickers
