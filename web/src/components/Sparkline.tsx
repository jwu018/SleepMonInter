// A tiny server-rendered trend line (plain SVG, no JavaScript sent to the browser).
// Used for "median RR per night" on the patient overview.

export function Sparkline({
  values,
  width = 240,
  height = 56,
  label,
}: {
  values: (number | null)[];
  width?: number;
  height?: number;
  label: string;
}) {
  const pts = values
    .map((v, i) => ({ v, i }))
    .filter((p): p is { v: number; i: number } => p.v != null);
  if (pts.length === 0) return null;

  const pad = 6;
  const min = Math.min(...pts.map((p) => p.v));
  const max = Math.max(...pts.map((p) => p.v));
  const span = max - min || 1;
  const x = (i: number) => pad + (i * (width - 2 * pad)) / Math.max(1, values.length - 1);
  const y = (v: number) => height - pad - ((v - min) / span) * (height - 2 * pad);
  const path = pts.map((p, k) => `${k === 0 ? "M" : "L"}${x(p.i)},${y(p.v)}`).join(" ");
  const last = pts[pts.length - 1];

  return (
    <svg width={width} height={height} role="img" aria-label={label} className="overflow-visible">
      <path d={path} fill="none" stroke="var(--chart-series-1)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
      {pts.map((p) => (
        // Surface-colored ring keeps dots legible where they sit on the line.
        <circle key={p.i} cx={x(p.i)} cy={y(p.v)} r={4} fill="var(--chart-series-1)" stroke="var(--surface)" strokeWidth={2} />
      ))}
      <text x={x(last.i) + 8} y={y(last.v) + 4} fontSize={12} fill="var(--foreground)">
        {last.v.toFixed(1)}
      </text>
    </svg>
  );
}
