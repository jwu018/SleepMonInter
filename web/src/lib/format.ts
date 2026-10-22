// Small display helpers shared by server and client components.

/** 465 -> "7 h 45 min" */
export function formatDuration(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  if (h === 0) return `${m} min`;
  return m === 0 ? `${h} h` : `${h} h ${m} min`;
}

/** null-safe fixed-decimal number, with a dash for missing values. */
export function formatNumber(value: number | null | undefined, digits = 1): string {
  return value == null ? "—" : value.toFixed(digits);
}

/** ISO string -> seconds since 1970, the x-axis unit uPlot expects for time scales. */
export function isoToUnixSeconds(iso: string): number {
  return Date.parse(iso) / 1000;
}

// --- Battery (simple linear model; the real discharge curve isn't linear) -------------

/** Below this the device is assumed to shut down. A typical Li-ion cutoff. */
export const BATTERY_EMPTY_MV = 3400;
/** A freshly charged pack. */
export const BATTERY_FULL_MV = 4200;

export interface BatteryEstimate {
  drop_mv: number;
  drain_mv_per_hour: number;
  /** Hours left at the end of the recording if it kept draining at the same rate. */
  remaining_hours: number | null;
  /** 0..1 position between empty and full, for the meter. */
  charge_fraction: number;
}

export function estimateBattery(
  startMv: number,
  endMv: number,
  durationMin: number,
): BatteryEstimate {
  const drop = startMv - endMv;
  const hours = durationMin / 60;
  const drain = hours > 0 ? drop / hours : 0;
  const remaining = drain > 0 ? Math.max(0, (endMv - BATTERY_EMPTY_MV) / drain) : null;
  const fraction = (endMv - BATTERY_EMPTY_MV) / (BATTERY_FULL_MV - BATTERY_EMPTY_MV);
  return {
    drop_mv: drop,
    drain_mv_per_hour: drain,
    remaining_hours: remaining,
    charge_fraction: Math.min(1, Math.max(0, fraction)),
  };
}
