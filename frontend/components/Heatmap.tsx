"use client";

import { ResponsiveContainer, Treemap } from "recharts";
import { usePortfolio } from "@/lib/hooks";
import Panel from "./ui/Panel";
import { fmtUsdCompact, fmtPct } from "@/lib/format";

const UP = [63, 185, 80];
const DOWN = [248, 81, 73];
const BASE = [24, 30, 42];

function clamp(n: number, lo: number, hi: number) {
  return Math.max(lo, Math.min(hi, n));
}

function fillFor(pnlPct: number): string {
  const target = pnlPct >= 0 ? UP : DOWN;
  const k = clamp(Math.abs(pnlPct) / 5, 0.14, 0.9);
  const c = BASE.map((b, i) => Math.round(b + (target[i] - b) * k));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

interface CellProps {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  depth?: number;
  name?: string;
  pnlPct?: number;
  marketValue?: number;
}

function Cell(props: CellProps) {
  const { x = 0, y = 0, width = 0, height = 0, depth = 0, name = "" } = props;
  if (depth !== 1) return null;
  const pnlPct = props.pnlPct ?? 0;
  const showText = width > 46 && height > 30;
  return (
    <g>
      <rect
        x={x}
        y={y}
        width={width}
        height={height}
        fill={fillFor(pnlPct)}
        stroke="var(--color-bg)"
        strokeWidth={2}
        rx={2}
      />
      {showText && (
        <>
          <text
            x={x + 6}
            y={y + 16}
            fill="var(--color-ink)"
            fontSize={12}
            fontWeight={600}
          >
            {name}
          </text>
          <text
            x={x + 6}
            y={y + 30}
            fill="rgba(230,237,243,0.75)"
            fontSize={10}
            style={{ fontVariantNumeric: "tabular-nums" }}
          >
            {fmtPct(pnlPct)}
          </text>
        </>
      )}
    </g>
  );
}

export default function Heatmap() {
  const { portfolio } = usePortfolio();
  const data = portfolio.positions.map((p) => ({
    name: p.ticker,
    size: p.marketValue,
    pnlPct: p.pctChange,
    marketValue: p.marketValue,
  }));

  return (
    <Panel
      title="Position Heatmap"
      right={
        <span className="tnum text-[10px] text-faint">
          {fmtUsdCompact(portfolio.positionsValue)} invested
        </span>
      }
      bodyClassName="p-2"
    >
      {data.length === 0 ? (
        <div className="flex h-full items-center justify-center text-xs text-faint">
          No positions yet — buy something to see it here.
        </div>
      ) : (
        <ResponsiveContainer width="100%" height="100%">
          <Treemap
            data={data}
            dataKey="size"
            content={<Cell />}
            isAnimationActive={false}
          />
        </ResponsiveContainer>
      )}
    </Panel>
  );
}
