"use client";

import { usePortfolio } from "@/lib/hooks";
import { useLiveTicks } from "@/lib/hooks";
import { fmtUsd, fmtSigned, fmtPct } from "@/lib/format";
import type { ConnectionStatus } from "@/lib/types";

const CONN: Record<ConnectionStatus, { color: string; label: string }> = {
  connected: { color: "var(--color-up)", label: "LIVE" },
  reconnecting: { color: "var(--color-accent)", label: "RECONNECTING" },
  disconnected: { color: "var(--color-down)", label: "OFFLINE" },
};

function Stat({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-end leading-tight">
      <span className="text-[10px] uppercase tracking-[0.14em] text-faint">
        {label}
      </span>
      <span className="tnum text-sm text-ink">{children}</span>
    </div>
  );
}

export default function Header() {
  const { portfolio } = usePortfolio();
  const { connection } = useLiveTicks();
  const conn = CONN[connection];
  const pnlUp = portfolio.unrealizedPnl >= 0;
  const pnlPct =
    portfolio.totalValue - portfolio.unrealizedPnl !== 0
      ? (portfolio.unrealizedPnl /
          (portfolio.totalValue - portfolio.unrealizedPnl)) *
        100
      : 0;

  return (
    <header className="flex items-center justify-between border-b border-border bg-panel px-4 py-2.5">
      <div className="flex items-baseline gap-3">
        <span className="text-lg font-bold tracking-tight">
          <span className="text-ink">Fin</span>
          <span className="text-accent">Ally</span>
        </span>
        <span className="hidden text-[10px] uppercase tracking-[0.22em] text-faint sm:inline">
          AI Trading Workstation
        </span>
      </div>

      <div className="flex items-center gap-5">
        <div className="flex flex-col items-end leading-tight">
          <span className="text-[10px] uppercase tracking-[0.14em] text-faint">
            Total Value
          </span>
          <span className="tnum text-lg font-semibold text-ink">
            {fmtUsd(portfolio.totalValue)}
          </span>
        </div>

        <Stat label="Unrealized P&L">
          <span style={{ color: pnlUp ? "var(--color-up)" : "var(--color-down)" }}>
            {fmtSigned(portfolio.unrealizedPnl)}{" "}
            <span className="text-xs">({fmtPct(pnlPct)})</span>
          </span>
        </Stat>

        <Stat label="Cash">{fmtUsd(portfolio.cash)}</Stat>

        <div className="flex items-center gap-2 border-l border-border pl-4">
          <span
            className="relative flex h-2.5 w-2.5"
            title={`Connection: ${conn.label}`}
          >
            <span
              className="absolute inline-flex h-full w-full animate-ping rounded-full opacity-60"
              style={{ backgroundColor: conn.color }}
            />
            <span
              className="relative inline-flex h-2.5 w-2.5 rounded-full"
              style={{ backgroundColor: conn.color }}
            />
          </span>
          <span
            className="text-[10px] font-semibold uppercase tracking-[0.14em]"
            style={{ color: conn.color }}
          >
            {conn.label}
          </span>
        </div>
      </div>
    </header>
  );
}
