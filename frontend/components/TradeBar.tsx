"use client";

import { useState } from "react";
import { useLiveTicks, usePortfolio, useWatchlist } from "@/lib/hooks";
import { fmtUsd } from "@/lib/format";
import type { TradeSide } from "@/lib/types";

export default function TradeBar() {
  const { selected } = useWatchlist();
  const { prices } = useLiveTicks();
  const { buy, sell } = usePortfolio();

  const [ticker, setTicker] = useState(selected);
  const [qty, setQty] = useState("10");
  const [result, setResult] = useState<{ ok: boolean; msg: string } | null>(
    null,
  );

  // Follow the selected ticker, but let the user override by typing.
  const [prevSelected, setPrevSelected] = useState(selected);
  if (selected !== prevSelected) {
    setPrevSelected(selected);
    setTicker(selected);
  }

  const price = prices[ticker.toUpperCase()]?.price ?? 0;
  const quantity = Number(qty);
  const est = price * (Number.isFinite(quantity) ? quantity : 0);

  async function trade(side: TradeSide) {
    const q = Number(qty);
    if (!ticker || !Number.isFinite(q) || q <= 0) {
      flash(false, "Enter a ticker and a positive quantity.");
      return;
    }
    const r = side === "buy" ? await buy(ticker, q) : await sell(ticker, q);
    flash(r.ok, r.message);
  }

  function flash(ok: boolean, msg: string) {
    setResult({ ok, msg });
    window.setTimeout(() => setResult(null), 3000);
  }

  return (
    <div className="flex flex-wrap items-center gap-2 border-t border-border bg-panel px-3 py-2">
      <span className="text-[10px] uppercase tracking-[0.14em] text-faint">
        Order
      </span>
      <input
        value={ticker}
        onChange={(e) => setTicker(e.target.value.toUpperCase())}
        aria-label="Ticker"
        maxLength={5}
        className="tnum w-20 rounded border border-border bg-bg px-2 py-1.5 text-sm uppercase outline-none focus:border-blue"
      />
      <input
        value={qty}
        onChange={(e) => setQty(e.target.value.replace(/[^0-9.]/g, ""))}
        aria-label="Quantity"
        inputMode="decimal"
        className="tnum w-24 rounded border border-border bg-bg px-2 py-1.5 text-sm outline-none focus:border-blue"
      />
      <span className="tnum text-xs text-muted">
        est. {fmtUsd(est)}
        {price > 0 && (
          <span className="text-faint"> @ {fmtUsd(price)}</span>
        )}
      </span>

      <div className="ml-auto flex items-center gap-2">
        {result && (
          <span
            className="max-w-[320px] truncate text-xs"
            style={{
              color: result.ok ? "var(--color-up)" : "var(--color-down)",
            }}
            title={result.msg}
          >
            {result.msg}
          </span>
        )}
        <button
          onClick={() => trade("buy")}
          className="rounded border border-up/40 bg-up/15 px-4 py-1.5 text-sm font-semibold text-up transition-colors hover:bg-up/25"
        >
          Buy
        </button>
        <button
          onClick={() => trade("sell")}
          className="rounded border border-down/40 bg-down/15 px-4 py-1.5 text-sm font-semibold text-down transition-colors hover:bg-down/25"
        >
          Sell
        </button>
      </div>
    </div>
  );
}
