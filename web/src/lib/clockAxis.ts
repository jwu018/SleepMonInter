// A shared "evening to morning" time axis for overlaying nights by clock time.
//
// Nights cross midnight, so plain hour-of-day (22, 23, 0, 1...) would jump backwards.
// Instead, x = hours since the noon before the night: 22:00 -> 10, 00:30 -> 12.5, 07:00 -> 19.
// Every night then sits on the same increasing axis, and "3 am" lines up across nights.
// Pure functions (no Date), so they're easy to test; callers pass local clock values.

/** Hours after noon for a local clock time. Times before noon belong to the night that began the previous evening. */
export function hoursAfterNoon(localHour: number, localMinute: number): number {
  const h = localHour + localMinute / 60;
  return h < 12 ? h + 12 : h - 12;
}

/** Axis label for an hours-after-noon value, e.g. 10 -> "10 pm", 12 -> "12 am", 19.5 -> "7:30 am". */
export function clockLabel(x: number): string {
  const totalMin = Math.round((((x + 12) % 24) + 24) % 24 * 60) % (24 * 60);
  const h24 = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  const suffix = h24 < 12 ? "am" : "pm";
  const h12 = h24 % 12 === 0 ? 12 : h24 % 12;
  return m === 0 ? `${h12} ${suffix}` : `${h12}:${String(m).padStart(2, "0")} ${suffix}`;
}

export interface NightOnClock {
  /** Hours after noon at the first minute, rounded to a whole minute. */
  start_x: number;
  values: (number | null)[]; // one per minute
}

/**
 * Put several nights on one shared minute grid by clock time.
 * Returns the x values (hours after noon) and one aligned array per night (null where a
 * night has no data at that clock minute).
 */
export function alignByClock(nights: NightOnClock[]): { x: number[]; series: (number | null)[][] } {
  if (nights.length === 0) return { x: [], series: [] };
  const startMin = nights.map((n) => Math.round(n.start_x * 60));
  const first = Math.min(...startMin);
  const last = Math.max(...nights.map((n, i) => startMin[i] + n.values.length));
  const x = Array.from({ length: last - first }, (_, k) => (first + k) / 60);
  const series = nights.map((n, i) =>
    x.map((_, k) => {
      const idx = first + k - startMin[i];
      return idx >= 0 && idx < n.values.length ? n.values[idx] : null;
    }),
  );
  return { x, series };
}
