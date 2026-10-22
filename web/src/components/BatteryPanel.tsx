import { BATTERY_EMPTY_MV, estimateBattery, formatNumber } from "@/lib/format";

// Battery at the END of the recording, read from the file. This is not live device status,
// and the label says so.
export function BatteryPanel({
  startMv,
  endMv,
  durationMin,
}: {
  startMv: number;
  endMv: number;
  durationMin: number;
}) {
  const est = estimateBattery(startMv, endMv, durationMin);
  const low = est.remaining_hours != null && est.remaining_hours < 2;

  return (
    <section className="rounded-lg border border-border bg-surface p-4">
      <h2 className="font-semibold">Battery</h2>
      <p className="text-xs text-muted">At end of recording, not live</p>

      <div className="mt-3 flex items-baseline gap-2">
        <span className="text-3xl font-semibold tabular">{(endMv / 1000).toFixed(2)} V</span>
        <span className="text-sm text-muted">from {(startMv / 1000).toFixed(2)} V at start</span>
      </div>

      {/* Meter: track and fill from the same hue family; fill = charge left above cutoff. */}
      <div
        className="mt-3 h-2 w-full overflow-hidden rounded-full bg-accent/20"
        role="meter"
        aria-label="Estimated charge remaining"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(est.charge_fraction * 100)}
      >
        <div className="h-full rounded-full bg-accent" style={{ width: `${est.charge_fraction * 100}%` }} />
      </div>

      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
        <dt className="text-muted">Drain rate</dt>
        <dd className="tabular">{formatNumber(est.drain_mv_per_hour, 0)} mV/h</dd>
        <dt className="text-muted">Est. life left</dt>
        <dd className="tabular">
          {est.remaining_hours == null ? "—" : `≈ ${formatNumber(est.remaining_hours, 1)} h`}
          {low && <span className="ml-2 text-xs font-medium">⚠ swap pack before next night</span>}
        </dd>
      </dl>
      <p className="mt-2 text-xs text-muted">
        Simple linear estimate down to a {BATTERY_EMPTY_MV / 1000} V cutoff.
      </p>
    </section>
  );
}
