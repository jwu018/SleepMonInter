import type { BatterySummary } from "@/lib/device/parseDeviceCsv";

// Battery left at the END of an uploaded recording: a battery outline filled green in
// proportion to the charge, with the percentage written on top.
// The percentage is the logger's own estimate (firmware LiPo voltage curve), not live status.

const SIZES = {
  sm: { body: "h-5 w-11", tip: "h-2 w-1", text: "text-[11px]" },
  lg: { body: "h-12 w-28", tip: "h-5 w-2", text: "text-lg" },
} as const;

export function BatteryIcon({
  battery,
  size = "sm",
}: {
  battery: BatterySummary | null;
  size?: keyof typeof SIZES;
}) {
  const s = SIZES[size];
  if (!battery) {
    return <span className="text-xs text-muted">Not logged</span>;
  }
  const pct = battery.end_pct;
  if (pct === null) {
    return <span className="text-xs text-muted">No valid reading</span>;
  }
  const clamped = Math.min(100, Math.max(0, pct));

  return (
    <span
      className="inline-flex items-center"
      role="meter"
      aria-label="Battery left at end of recording"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={clamped}
      title={`${clamped}% (${battery.end_v?.toFixed(2)} V) at end of recording`}
    >
      <span className={`relative overflow-hidden rounded-[4px] border-2 border-foreground/70 ${s.body}`}>
        {/* Green fill: width = charge left. */}
        <span className="absolute inset-y-0 left-0 bg-status-good" style={{ width: `${clamped}%` }} />
        {/* Percentage on top of the fill. The light halo keeps it readable over green or empty. */}
        <span
          className={`absolute inset-0 grid place-items-center font-semibold tabular text-foreground ${s.text}`}
          style={{ textShadow: "0 0 3px var(--background), 0 0 3px var(--background)" }}
        >
          {clamped}%
        </span>
      </span>
      <span className={`rounded-r-sm bg-foreground/70 ${s.tip}`} aria-hidden />
    </span>
  );
}
