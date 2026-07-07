# FinAlly — AI Trading Workstation

A visually stunning AI-powered trading workstation that streams live market data, simulates portfolio trading, and integrates an LLM chat assistant that can analyze positions and execute trades via natural language.

Built entirely by coding agents as a capstone project for an agentic AI coding course.

## Status

In progress. Only the **market data backend** is built so far — see [`planning/MARKET_DATA_SUMMARY.md`](planning/MARKET_DATA_SUMMARY.md) for details. The frontend, portfolio/trading API, LLM chat, database, and Docker packaging described below are not yet implemented. See [`planning/PLAN.md`](planning/PLAN.md) for the full spec.

## Features (planned)

- **Live price streaming** via SSE with green/red flash animations
- **Simulated portfolio** — $10k virtual cash, market orders, instant fills
- **Portfolio visualizations** — heatmap (treemap), P&L chart, positions table
- **AI chat assistant** — analyzes holdings, suggests and auto-executes trades
- **Watchlist management** — track tickers manually or via AI
- **Dark terminal aesthetic** — Bloomberg-inspired, data-dense layout

## Architecture (target)

Single Docker container serving everything on port 8000:

- **Frontend**: Next.js (static export) with TypeScript and Tailwind CSS
- **Backend**: FastAPI (Python/uv) with SSE streaming
- **Database**: SQLite with lazy initialization
- **AI**: LiteLLM → OpenRouter (Cerebras inference) with structured outputs
- **Market data**: Built-in GBM simulator (default) or Massive API (optional)

Today only the market data piece exists, runnable directly with `uv` — there's no Dockerfile, frontend, database, or API layer in the repo yet.

## Quick Start

```bash
cd backend
uv sync --extra dev

# Run the test suite
uv run pytest -v

# Live terminal demo of the simulator (Rich dashboard, 10 tickers, sparklines)
uv run market_data_demo.py
```

See [`backend/README.md`](backend/README.md) and [`backend/CLAUDE.md`](backend/CLAUDE.md) for full backend developer instructions.

Once the frontend, database, and API layer exist, the plan is a one-command Docker flow (see [`planning/PLAN.md`](planning/PLAN.md) §11) — not functional yet, since no Dockerfile or `.env.example` exists in the repo:

```bash
cp .env.example .env
# Add your OPENROUTER_API_KEY to .env
docker build -t finally .
docker run -v finally-data:/app/db -p 8000:8000 --env-file .env finally
# Open http://localhost:8000
```

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `OPENROUTER_API_KEY` | Yes | OpenRouter API key for AI chat |
| `MASSIVE_API_KEY` | No | Massive (Polygon.io) key for real market data; omit to use simulator |
| `LLM_MOCK` | No | Set `true` for deterministic mock LLM responses (testing) |

## Project Structure

```
finally/
├── backend/     # FastAPI uv project (market data subsystem built; portfolio/chat/db pending)
└── planning/    # Project documentation and agent contracts
```

`frontend/`, `test/`, `db/`, and `scripts/` are planned per [`planning/PLAN.md`](planning/PLAN.md) but not yet created.

## License

See [LICENSE](LICENSE).
