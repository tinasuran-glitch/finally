"use client";

import {
  Area,
  AreaChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useLiveTicks, useWatchlist } from "@/lib/hooks";
import Panel from "./ui/Panel";
import PriceFlash from "./ui/PriceFlash";
import { fmtPrice, fmtPct } from "@/lib/format";

interface TipProps {
  active?: boolean;
  payload?: { value: number }[];
}

function ChartTip({ active, payload }: TipProps) {
  if (!active || !payload?.length) return null;
  return (
    <div className="tnum rounded border border-border-strong bg-panel px-2 py-1 text-xs text-ink shadow-lg">
      ${fmtPrice(payload[0].value)}
    </div>
  );
}

export default function MainChart() {
  const { selected } = useWatchlist();
  const { prices } = useLiveTicks();
  const tick = prices[selected];

  const data = (tick?.history ?? []).map((price, i) => ({ i, price }));
  const up = data.length > 1 && data[data.length - 1].price >= data[0].price;
  const color = up ? "var(--color-up)" : "var(--color-down)";

  const dayChange = tick?.sessionOpen
    ? ((tick.price - tick.sessionOpen) / tick.sessionOpen) * 100
    : 0;

  return (
    <Panel
      title="Price"
      right={
        tick ? (
          <div className="flex items-baseline gap-2">
            <span className="text-sm font-semibold text-ink">{selected}</span>
            <PriceFlash value={tick.price} className="tnum text-sm">
              ${fmtPrice(tick.price)}
            </PriceFlash>
            <span
              className="tnum text-xs"
              style={{
                color: dayChange >= 0 ? "var(--color-up)" : "var(--color-down)",
              }}
            >
              {fmtPct(dayChange)}
            </span>
          </div>
        ) : null
      }
      bodyClassName="p-2"
    >
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id="mainFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity="0.25" />
              <stop offset="100%" stopColor={color} stopOpacity="0" />
            </linearGradient>
          </defs>
          <XAxis dataKey="i" hide />
          <YAxis
            orientation="right"
            width={56}
            domain={["dataMin", "dataMax"]}
            tick={{ fill: "var(--color-faint)", fontSize: 10 }}
            tickFormatter={(v: number) => fmtPrice(v)}
            axisLine={false}
            tickLine={false}
          />
          <Tooltip
            content={<ChartTip />}
            cursor={{ stroke: "var(--color-border-strong)", strokeWidth: 1 }}
          />
          <Area
            type="monotone"
            dataKey="price"
            stroke={color}
            strokeWidth={2}
            fill="url(#mainFill)"
            isAnimationActive={false}
            dot={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </Panel>
  );
}
