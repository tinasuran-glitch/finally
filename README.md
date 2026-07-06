# FinAlly — AI Trading Workstation

FinAlly (Finance Ally) is an AI-powered trading workstation: a Bloomberg-terminal-style
UI that streams live (simulated) market data, lets you trade a virtual $10,000 portfolio,
and includes an LLM chat assistant that can analyze your positions and place trades on
your behalf.

This is the capstone project for an agentic AI coding course — built by coding agents
coordinating through the docs in [`planning/`](planning/PLAN.md).

> **Status:** planning stage. The architecture, schema, and API surface are specified in
> [`planning/PLAN.md`](planning/PLAN.md); `frontend/` and `backend/` have not been built yet.

## What it does

- Live-updating watchlist with flashing price ticks and sparkline mini-charts
- Detailed chart view for a selected ticker
- Portfolio heatmap (treemap) and P&L history chart
- Positions table with unrealized P&L
- Instant-fill market order trading (buy/sell, no fees, no confirmation)
- AI chat assistant that can explain your portfolio, suggest trades, and execute
  trades or watchlist changes automatically

## Architecture

Single Docker container, single port (8000):

- **Frontend**: Next.js (TypeScript), built as a static export, served by the backend
- **Backend**: FastAPI (Python), managed with `uv`
- **Database**: SQLite (`db/finally.db`), volume-mounted, lazily initialized/seeded
- **Real-time data**: Server-Sent Events (`/api/stream/prices`)
- **Market data**: built-in GBM simulator by default, or real data via the Massive
  (Polygon.io) API if `MASSIVE_API_KEY` is set
- **AI**: LiteLLM → OpenRouter (Cerebras inference), structured JSON output for chat +
  trade execution

Full details, schema, and API endpoints are in [`planning/PLAN.md`](planning/PLAN.md).

## Getting started

Once built, the app will run via a single script:

```bash
./scripts/start_mac.sh      # macOS/Linux
./scripts/start_windows.ps1 # Windows
```

This builds/starts the Docker container and opens `http://localhost:8000` — no login
required. Configuration lives in a project-root `.env` (see `.env.example`):

```bash
OPENROUTER_API_KEY=   # required for the AI chat assistant
MASSIVE_API_KEY=      # optional, enables real market data instead of the simulator
LLM_MOCK=false         # set true for deterministic mock LLM responses (used in E2E tests)
```

## Repository layout

```
finally/
├── frontend/     # Next.js TypeScript app (static export)
├── backend/      # FastAPI uv project — API, DB, market data, LLM integration
├── planning/     # Project spec and agent-facing docs (PLAN.md is the source of truth)
├── scripts/      # Start/stop scripts wrapping Docker
├── test/         # Playwright E2E tests
└── db/           # Runtime volume mount point for the SQLite database
```

## License

See [LICENSE](LICENSE).
