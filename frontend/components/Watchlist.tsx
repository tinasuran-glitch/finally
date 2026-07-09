"use client";

import { useState } from "react";
import { useLiveTicks, useWatchlist } from "@/lib/hooks";
import Panel from "./ui/Panel";
import Sparkline from "./ui/Sparkline";
import PriceFlash from "./ui/PriceFlash";
import { fmtPrice, fmtPct } from "@/lib/format";
import type { Tick } from "@/lib/types";

function dayChangePct(t: Tick): number {
  return t.sessionOpen ? ((t.price - t.sessionOpen) / t.sessionOpen) * 100 : 0;
}

function AddTicker({ onAdd }: { onAdd: (t: string) => boolean }) {
  const [value, setValue] = useState("");
  const [error, setError] = useState(false);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!value.trim()) return;
    const ok = onAdd(value);
    if (ok) setValue("");
    else {
      setError(true);
      window.setTimeout(() => setError(false), 900);
    }
  }

  return (
    <form onSubmit={submit} className="flex items-center gap-1">
      <input
        value={value}
        onChange={(e) => setValue(e.target.value.toUpperCase())}
        placeholder="ADD"
        maxLength={5}
        aria-label="Add ticker to watchlist"
        className={`tnum w-16 rounded border bg-bg px-2 py-1 text-[11px] uppercase tracking-wide outline-none placeholder:text-faint focus:border-blue ${
          error ? "border-down" : "border-border"
        }`}
      />
      <button
        type="submit"
        className="rounded border border-border px-2 py-1 text-[11px] font-semibold text-muted transition-colors hover:border-blue hover:text-blue"
      >
        +
      </button>
    </form>
  );
}

export default function Watchlist() {
  const { prices } = useLiveTicks();
  const { watchlist, selected, select, addTicker, removeTicker } =
    useWatchlist();

  return (
    <Panel
      title="Watchlist"
      right={<AddTicker onAdd={addTicker} />}
      bodyClassName="overflow-y-auto"
    >
      <div className="grid grid-cols-[1fr_auto_auto_auto] items-center gap-x-3 border-b border-border px-3 py-1.5 text-[10px] uppercase tracking-[0.12em] text-faint">
        <span>Symbol</span>
        <span className="text-right">Last</span>
        <span className="text-right">Chg%</span>
        <span className="pr-6 text-right">Trend</span>
      </div>
      <ul>
        {watchlist.map((ticker) => {
          const t = prices[ticker];
          if (!t) return null;
          const dc = dayChangePct(t);
          const up = dc >= 0;
          const isSel = ticker === selected;
          return (
            <li
              key={ticker}
              onClick={() => select(ticker)}
              className={`group grid cursor-pointer grid-cols-[1fr_auto_auto_auto] items-center gap-x-3 border-l-2 px-3 py-1.5 transition-colors ${
                isSel
                  ? "border-accent bg-white/[0.04]"
                  : "border-transparent hover:bg-white/[0.02]"
              }`}
            >
              <span className="text-[13px] font-semibold text-ink">
                {ticker}
              </span>
              <PriceFlash value={t.price} className="tnum text-right text-[13px]">
                {fmtPrice(t.price)}
              </PriceFlash>
              <span
                className="tnum w-16 text-right text-xs"
                style={{ color: up ? "var(--color-up)" : "var(--color-down)" }}
              >
                {fmtPct(dc)}
              </span>
              <div className="flex items-center gap-1 pl-1">
                <Sparkline data={t.history} />
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    removeTicker(ticker);
                  }}
                  aria-label={`Remove ${ticker}`}
                  className="w-4 text-faint opacity-0 transition-opacity hover:text-down group-hover:opacity-100"
                >
                  ×
                </button>
              </div>
            </li>
          );
        })}
      </ul>
    </Panel>
  );
}
