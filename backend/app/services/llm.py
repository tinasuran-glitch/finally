"""LLM chat brain for FinAlly.

Builds the prompt from portfolio context and conversation history, then calls
the model (via LiteLLM -> OpenRouter -> Cerebras) requesting structured JSON
output. When ``LLM_MOCK`` is truthy, a deterministic rule-based mock is used
instead so tests and no-key development are fast, free, and reproducible.
"""

from __future__ import annotations

import os
import re

from litellm import completion
from pydantic import BaseModel

MODEL = "openrouter/openai/gpt-oss-120b"
EXTRA_BODY = {"provider": {"order": ["cerebras"]}}

SYSTEM_PROMPT = (
    "You are FinAlly, an AI trading assistant embedded in a simulated trading "
    "workstation. Analyze the user's portfolio composition, risk concentration, "
    "and P&L. Suggest trades with clear reasoning, execute trades when the user "
    "asks or agrees, and manage the watchlist proactively. Be concise and "
    "data-driven. You are operating on a simulated portfolio with fake money, so "
    "you may execute trades directly without asking for confirmation. "
    "Always respond with valid structured JSON matching the required schema: a "
    "conversational `message` string, an optional `trades` array of "
    "{ticker, side ('buy'|'sell'), quantity}, and an optional "
    "`watchlist_changes` array of {ticker, action ('add'|'remove')}."
)


# --- Structured output schema -------------------------------------------

class Trade(BaseModel):
    ticker: str
    side: str  # "buy" | "sell"
    quantity: float


class WatchlistChange(BaseModel):
    ticker: str
    action: str  # "add" | "remove"


class ChatResponse(BaseModel):
    message: str
    trades: list[Trade] = []
    watchlist_changes: list[WatchlistChange] = []


# --- Prompt construction -------------------------------------------------

def _format_context(portfolio: dict, watchlist: list[dict]) -> str:
    """Render portfolio and watchlist state as a compact text block."""
    lines = [
        f"Cash balance: ${portfolio['cash_balance']:.2f}",
        f"Total portfolio value: ${portfolio['total_value']:.2f}",
    ]
    positions = portfolio.get("positions", [])
    if positions:
        lines.append("Positions:")
        for p in positions:
            lines.append(
                f"  {p['ticker']}: {p['quantity']} @ avg ${p['avg_cost']:.2f}, "
                f"now ${p['current_price']:.2f}, "
                f"P&L ${p['unrealized_pnl']:.2f} ({p['pnl_percent']:.2f}%)"
            )
    else:
        lines.append("Positions: none")

    if watchlist:
        lines.append("Watchlist:")
        for w in watchlist:
            price = f"${w['price']:.2f}" if w.get("price") is not None else "n/a"
            lines.append(f"  {w['ticker']}: {price}")
    return "\n".join(lines)


def _build_messages(
    message: str,
    portfolio: dict,
    watchlist: list[dict],
    history: list[dict],
) -> list[dict]:
    """Assemble the messages list: system + context + history + new message."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "system",
            "content": "Current portfolio context:\n" + _format_context(portfolio, watchlist),
        },
    ]
    for msg in history:
        role = msg["role"] if msg["role"] in ("user", "assistant") else "user"
        messages.append({"role": role, "content": msg["content"]})
    messages.append({"role": "user", "content": message})
    return messages


# --- Public entry point --------------------------------------------------

def generate_response(
    message: str,
    portfolio: dict,
    watchlist: list[dict],
    history: list[dict],
) -> ChatResponse:
    """Produce a structured chat response for the user's message.

    Uses the deterministic mock when ``LLM_MOCK`` is truthy, otherwise calls
    the real model.
    """
    if os.getenv("LLM_MOCK", "").lower() == "true":
        return _mock_response(message, portfolio)

    messages = _build_messages(message, portfolio, watchlist, history)
    response = completion(
        model=MODEL,
        messages=messages,
        response_format=ChatResponse,
        reasoning_effort="low",
        extra_body=EXTRA_BODY,
    )
    content = response.choices[0].message.content
    return ChatResponse.model_validate_json(content)


# --- Deterministic mock --------------------------------------------------

# Supported command patterns (case-insensitive), matched anywhere in the text:
#   buy <qty> <TICKER>      -> trades: [{ticker, side: buy, quantity}]
#   sell <qty> <TICKER>     -> trades: [{ticker, side: sell, quantity}]
#   add <TICKER>            -> watchlist_changes: [{ticker, action: add}]
#   remove <TICKER>         -> watchlist_changes: [{ticker, action: remove}]
# Multiple commands in one message are all captured. TICKER = 1-5 letters.
# If nothing matches, a generic portfolio summary is returned.

_TRADE_RE = re.compile(r"\b(buy|sell)\s+(\d+(?:\.\d+)?)\s+([A-Za-z]{1,5})\b", re.IGNORECASE)
_WATCH_RE = re.compile(
    r"\b(add|remove)\s+([A-Za-z]{1,5})\b(?:\s+(?:to|from)\s+(?:the\s+)?watchlist)?",
    re.IGNORECASE,
)


def _mock_response(message: str, portfolio: dict) -> ChatResponse:
    """Rule-based deterministic response for tests and keyless dev."""
    trades: list[Trade] = []
    watchlist_changes: list[WatchlistChange] = []
    parts: list[str] = []

    for side, qty, ticker in _TRADE_RE.findall(message):
        trades.append(
            Trade(ticker=ticker.upper(), side=side.lower(), quantity=float(qty))
        )
        parts.append(f"{side.lower()} {qty} {ticker.upper()}")

    for action, ticker in _WATCH_RE.findall(message):
        watchlist_changes.append(
            WatchlistChange(ticker=ticker.upper(), action=action.lower())
        )
        parts.append(f"{action.lower()} {ticker.upper()} on the watchlist")

    if parts:
        text = "[MOCK] Executing: " + ", ".join(parts) + "."
    else:
        text = (
            f"[MOCK] Your portfolio is worth ${portfolio['total_value']:.2f} "
            f"with ${portfolio['cash_balance']:.2f} in cash and "
            f"{len(portfolio.get('positions', []))} open position(s)."
        )

    return ChatResponse(
        message=text, trades=trades, watchlist_changes=watchlist_changes
    )
