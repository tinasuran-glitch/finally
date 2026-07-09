"use client";

import { usePortfolio, useWatchlist } from "@/lib/hooks";
import Panel from "./ui/Panel";
import PriceFlash from "./ui/PriceFlash";
import { fmtPrice, fmtQty, fmtSigned, fmtPct } from "@/lib/format";

export default function PositionsTable() {
  const { portfolio } = usePortfolio();
  const { selected, select } = useWatchlist();

  return (
    <Panel
      title="Positions"
      right={
        <span className="tnum text-[10px] text-faint">
          {portfolio.positions.length} open
        </span>
      }
      bodyClassName="overflow-auto"
    >
      <table className="w-full text-[13px]">
        <thead className="sticky top-0 bg-panel">
          <tr className="text-[10px] uppercase tracking-[0.12em] text-faint">
            <th className="px-2 py-1.5 text-left font-medium">Symbol</th>
            <th className="px-2 py-1.5 text-right font-medium">Qty</th>
            <th className="px-2 py-1.5 text-right font-medium">Avg</th>
            <th className="px-2 py-1.5 text-right font-medium">Last</th>
            <th className="px-2 py-1.5 text-right font-medium">P&L</th>
            <th className="px-2 py-1.5 text-right font-medium">%</th>
          </tr>
        </thead>
        <tbody>
          {portfolio.positions.length === 0 && (
            <tr>
              <td colSpan={6} className="px-3 py-6 text-center text-xs text-faint">
                You hold no positions. Use the trade bar or ask FinAlly to buy.
              </td>
            </tr>
          )}
          {portfolio.positions.map((p) => {
            const up = p.unrealizedPnl >= 0;
            const c = up ? "var(--color-up)" : "var(--color-down)";
            return (
              <tr
                key={p.ticker}
                onClick={() => select(p.ticker)}
                className={`cursor-pointer border-t border-border/60 transition-colors hover:bg-white/[0.02] ${
                  p.ticker === selected ? "bg-white/[0.03]" : ""
                }`}
              >
                <td className="px-2 py-1.5 font-semibold text-ink">
                  {p.ticker}
                </td>
                <td className="tnum px-2 py-1.5 text-right text-muted">
                  {fmtQty(p.quantity)}
                </td>
                <td className="tnum px-2 py-1.5 text-right text-muted">
                  {fmtPrice(p.avgCost)}
                </td>
                <td className="px-2 py-1.5 text-right">
                  <PriceFlash value={p.currentPrice} className="tnum">
                    {fmtPrice(p.currentPrice)}
                  </PriceFlash>
                </td>
                <td className="tnum px-2 py-1.5 text-right" style={{ color: c }}>
                  {fmtSigned(p.unrealizedPnl)}
                </td>
                <td className="tnum px-2 py-1.5 text-right" style={{ color: c }}>
                  {fmtPct(p.pctChange)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </Panel>
  );
}
