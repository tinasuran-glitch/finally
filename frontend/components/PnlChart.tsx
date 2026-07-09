"use client";

import {
  Area,
  AreaChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { usePortfolio } from "@/lib/hooks";
import Panel from "./ui/Panel";
import { fmtUsd, fmtUsdCompact, fmtSigned } from "@/lib/format";

interface TipProps {
  active?: boolean;
  payload?: { value: number; payload: { t: number } }[];
}

function Tip({ active, payload }: TipProps) {
  if (!active || !payload?.length) return null;
  const p = payload[0];
  return (
    <div className="rounded border border-border-strong bg-panel px-2 py-1 text-xs shadow-lg">
      <div className="tnum text-ink">{fmtUsd(p.value)}</div>
      <div className="tnum text-[10px] text-faint">
        {new Date(p.payload.t).toLocaleTimeString("en-US", {
          hour: "2-digit",
          minute: "2-digit",
        })}
      </div>
    </div>
  );
}

export default function PnlChart() {
  const { pnlHistory } = usePortfolio();
  const first = pnlHistory[0]?.value ?? 0;
  const last = pnlHistory[pnlHistory.length - 1]?.value ?? 0;
  const up = last >= first;
  const color = up ? "var(--color-up)" : "var(--color-down)";
  const delta = last - first;

  return (
    <Panel
      title="Portfolio Value"
      right={
        <span
          className="tnum text-xs"
          style={{ color }}
          title="Change this session"
        >
          {fmtSigned(delta)}
        </span>
      }
      bodyClassName="p-2"
    >
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart
          data={pnlHistory}
          margin={{ top: 8, right: 8, bottom: 0, left: 0 }}
        >
          <defs>
            <linearGradient id="pnlFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity="0.22" />
              <stop offset="100%" stopColor={color} stopOpacity="0" />
            </linearGradient>
          </defs>
          <XAxis dataKey="t" hide />
          <YAxis
            orientation="right"
            width={44}
            domain={["dataMin", "dataMax"]}
            tick={{ fill: "var(--color-faint)", fontSize: 10 }}
            tickFormatter={(v: number) => fmtUsdCompact(v)}
            axisLine={false}
            tickLine={false}
          />
          <Tooltip
            content={<Tip />}
            cursor={{ stroke: "var(--color-border-strong)", strokeWidth: 1 }}
          />
          <Area
            type="monotone"
            dataKey="value"
            stroke={color}
            strokeWidth={2}
            fill="url(#pnlFill)"
            isAnimationActive={false}
            dot={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </Panel>
  );
}
