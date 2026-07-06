# Code Review Feedback for `planning/PLAN.md`

## Findings

### ~~Critical - real API key is embedded in tracked documentation~~ (Resolved)
`planning/PLAN.md:125`

`planning/PLAN.md:125` now contains only a placeholder (`OPENROUTER_API_KEY=your-openrouter-api-key-here`). No real key is present in tracked documentation.

### High - LLM tool/skill reference is inconsistent and likely to block implementation
`planning/PLAN.md:284`, `planning/PLAN.md:295`, `planning/PLAN.md:468`

Section 9 instructs agents to use a `cerebras-inference` skill, while the review notes say the intended skill is `cerebras`. In the currently available skill list for this workspace, I do not see either skill exposed. Agents following the plan may fail at the LLM integration step or invent the integration details. The plan should name the exact available skill or replace the skill dependency with concrete LiteLLM/OpenRouter implementation instructions.

### Medium - arbitrary watchlist additions conflict with fixed simulator seeds
`planning/PLAN.md:31`, `planning/PLAN.md:156`, `planning/PLAN.md:267`

The plan allows users and the AI to add tickers, but the simulator description only defines realistic seed prices for a known set. The backend contract needs to specify what happens for unknown symbols: reject them, lazily create a simulated instrument with a generated seed price, or validate against the real data provider. Without this, the frontend, simulator, and trade validation can diverge.

### Medium - trade execution depends on unstated price availability behavior
`planning/PLAN.md:260`, `planning/PLAN.md:267`, `planning/PLAN.md:328`

Trades fill at the current price, but the plan does not define behavior when a ticker has no cached price yet, has a stale price, or was just added to the watchlist. The API contract should state whether trades are rejected until a fresh quote exists, whether the backend synchronously initializes a quote, and what error shape the frontend/chat should display.

### Medium - "latest prices" from REST and SSE source of truth are underspecified
`planning/PLAN.md:169`, `planning/PLAN.md:178`, `planning/PLAN.md:266`, `planning/PLAN.md:355`

`GET /api/watchlist` returns latest prices, while SSE also pushes prices and the frontend accumulates chart/sparkline history from SSE. The plan should explicitly define first-paint behavior: REST should likely provide the initial snapshot, then SSE becomes the source of truth. This matters for avoiding duplicate polling, inconsistent price flashes, and charts that reset after watchlist mutations.

### Low - fractional-share support is not carried through to the UI/API contract
`planning/PLAN.md:214`, `planning/PLAN.md:224`, `planning/PLAN.md:260`, `planning/PLAN.md:360`

The database supports fractional quantities, but the API and trade bar do not say whether decimals are allowed, what precision is accepted, or how invalid/zero/negative values are handled. Add these constraints so backend validation and frontend input behavior match.

## Open Questions

- Should Massive API failures fall back to simulator prices per ticker, freeze the last known price, or surface degraded status globally?
- Should portfolio snapshots include cash-only snapshots before the first trade so the P&L chart is non-empty on first launch?
- Should AI auto-executed trades require a stricter validation path than manual trades, even in simulated mode, to prevent ambiguous prompts from producing surprising actions?

## Summary

The plan is strong as a product and architecture brief, but it needs a tighter backend contract before implementation. Fix the exposed secret first, then clarify ticker lifecycle, quote freshness, REST-vs-SSE ownership, and LLM integration instructions.
