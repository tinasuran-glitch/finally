# Fly.io Deployment — Plan & Record

**Status:** Deployed and verified end-to-end on 2026-07-10, then torn down on 2026-07-10 (`flyctl apps destroy finally-trading`) to stop incurring cost while a code change is pending on a branch. App, machine, and volume were all deleted — the setup below is a from-scratch redeploy procedure, not a running deployment.

**Live URL:** https://finally-trading.fly.dev (currently offline — app no longer exists)

## Why

FinAlly previously only ran locally via Docker (`scripts/start_mac.sh`, PLAN.md §11). This puts it on the public internet instead of `localhost`, using the exact same Docker image the local setup already builds — no application code changes were needed.

## Architecture

The existing single-container image maps directly onto Fly.io's model:

| Local (Docker Compose) | Fly.io |
|---|---|
| `docker-compose.yml` build | Same `Dockerfile`, built by Fly's remote (Depot) builder |
| `./db:/app/db` bind mount | Fly Volume `finally_data` (1 GB, region `iad`) mounted at `/app/db` |
| `.env` file via `env_file:` | `fly secrets set` (encrypted, not in git) |
| `-p 8000:8000` | `[http_service] internal_port = 8000`, Fly terminates TLS and proxies in |

## Key constraint: single machine only

Fly Volumes are single-attach — only one machine can mount `finally_data` at a time. The app also uses SQLite with a single hardcoded `user_id="default"`. **Never run `fly scale count 2+`** — a second machine could not attach the same volume, and even if it could, SQLite has one writer. This app is meant to stay at exactly one machine.

## `fly.toml` (committed at repo root)

```toml
app = "finally-trading"
primary_region = "iad"

[build]

[http_service]
  internal_port = 8000
  force_https = true
  auto_stop_machines = true
  auto_start_machines = true
  min_machines_running = 0

[[http_service.checks]]
  grace_period = "10s"
  interval = "15s"
  method = "GET"
  timeout = "5s"
  path = "/api/health"

[[mounts]]
  source = "finally_data"
  destination = "/app/db"

[[vm]]
  memory = "512mb"
  cpu_kind = "shared"
  cpus = 1
```

- **Scale-to-zero** (`min_machines_running = 0`): the machine stops after a period of inactivity and cold-starts (a few seconds) on the next request. Chosen for cost over always-on latency — this is a demo/personal app, not something needing to be instantly warm at all times.
- Health checks hit the existing `/api/health` route — no new endpoint was added.

## One-time setup (already done)

```bash
# Install & auth (interactive, browser-based — must be run by a human, not an agent)
curl -L https://fly.io/install.sh | sh
flyctl auth login

# Create the app and its persistent volume
flyctl apps create finally-trading
flyctl volumes create finally_data --region iad --size 1 -a finally-trading

# Push the LLM key as an encrypted secret (never written to fly.toml or git)
flyctl secrets set OPENROUTER_API_KEY=<value> -a finally-trading
```

`MASSIVE_API_KEY` and `LLM_MOCK` are intentionally left unset in Fly secrets, matching the local `.env`: blank `MASSIVE_API_KEY` → market simulator is used; unset `LLM_MOCK` defaults to `false` → real LLM calls via OpenRouter/Cerebras.

## Redeploying after a code change

```bash
flyctl deploy -a finally-trading
```

Builds the current `Dockerfile` fresh on Fly's remote builder and does a rolling replace of the single machine. The volume (and its data) is untouched by a deploy.

## Verification performed at initial deploy

- `GET /api/health` → `{"status":"ok"}`
- `GET /api/watchlist` → all 10 default tickers with live simulator prices
- Browser load of `https://finally-trading.fly.dev`: watchlist, $10k cash, `LIVE` SSE connection indicator, sparklines populating in real time
- `POST /api/portfolio/trade` (buy, then sell) → cash and position updated correctly, then restored to the clean seed state ($9,999.60 cash after fees-free round trip — the ~$0.40 delta is realized market movement between the buy and sell ticks, not a bug)
- `POST /api/chat` with a real (non-`LLM_MOCK`) message → genuine LLM-generated response, confirming `OPENROUTER_API_KEY` is live
- `flyctl machine restart` followed by `GET /api/portfolio` → position/cash state survived the restart, confirming the volume is correctly attached and persistent

## Known non-blocking issue

A React hydration warning (minified error #418) appears in the browser console on initial page load. The page renders and functions correctly despite it — not investigated further as it's a pre-existing frontend quirk unrelated to the deployment itself, not a Fly-specific issue.

## Follow-ups (not done, optional)

- Custom domain: `flyctl certs add <domain>` + a DNS record, in place of `*.fly.dev`.
- `flyctl ips allocate-v4` for a dedicated IPv4 (currently on Fly's shared IPv4 + dedicated IPv6).

## Redeploying from scratch (current state)

The app was fully destroyed, including the volume — the seeded $10k / no-positions state will be fresh again on next deploy (no data survived the teardown). To bring it back up: rerun the "One-time setup" commands above in order (`apps create` → `volumes create` → `secrets set`), then `flyctl deploy -a finally-trading`. If `finally-trading` is no longer available as an app name, pick a new one and update `app =` in `fly.toml` (repo root) to match before deploying.
