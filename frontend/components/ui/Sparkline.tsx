// Hand-rolled SVG sparkline — no chart lib, cheap to re-render every tick.

interface SparklineProps {
  data: number[];
  width?: number;
  height?: number;
  className?: string;
}

export default function Sparkline({
  data,
  width = 96,
  height = 28,
  className = "",
}: SparklineProps) {
  if (data.length < 2) {
    return <svg width={width} height={height} className={className} aria-hidden />;
  }

  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const pad = 2;
  const w = width - pad * 2;
  const h = height - pad * 2;
  const stepX = w / (data.length - 1);

  const y = (v: number) => pad + h - ((v - min) / range) * h;
  const points = data.map((v, i) => `${pad + i * stepX},${y(v)}`).join(" ");
  const up = data[data.length - 1] >= data[0];
  const stroke = up ? "var(--color-up)" : "var(--color-down)";

  const areaPoints = `${pad},${pad + h} ${points} ${pad + w},${pad + h}`;
  const gid = `spark-${up ? "u" : "d"}`;

  return (
    <svg
      width={width}
      height={height}
      className={className}
      aria-hidden
      preserveAspectRatio="none"
    >
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={stroke} stopOpacity="0.28" />
          <stop offset="100%" stopColor={stroke} stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon points={areaPoints} fill={`url(#${gid})`} />
      <polyline
        points={points}
        fill="none"
        stroke={stroke}
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}
