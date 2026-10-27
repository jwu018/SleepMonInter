// Helpers for drawing an uploaded recording: shrink a window of samples to a drawable
// number of points, and turn elapsed time into device-clock time.
// No imports, so it runs in the browser and under `node --test`.

export interface TracePoints {
  /** Seconds since the recording started. */
  x: number[];
  /** null breaks the line: a gap in the data (or a blank value). */
  y: (number | null)[];
  resolution: "raw" | "envelope";
}

const GAP_MS = 1000; // matches the data-gap rule in docs/DEVICE_FORMAT.md

/** First index i with values[i] >= target (values sorted ascending). */
function lowerBound(values: Float64Array, target: number): number {
  let lo = 0;
  let hi = values.length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (values[mid] < target) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/**
 * Samples in [startMs, endMs) as at most ~maxPoints points.
 * Zoomed in: every sample. Zoomed out: each bucket contributes its min and max, so
 * short spikes and the full breath depth stay visible (plain "every Nth sample" hides them).
 */
export function tracePoints(
  elapsedMs: Float64Array,
  values: Float64Array,
  startMs: number,
  endMs: number,
  maxPoints: number,
): TracePoints {
  const first = lowerBound(elapsedMs, startMs);
  const last = lowerBound(elapsedMs, endMs);
  const count = last - first;
  const x: number[] = [];
  const y: (number | null)[] = [];

  if (count <= maxPoints) {
    for (let i = first; i < last; i++) {
      if (i > first && elapsedMs[i] - elapsedMs[i - 1] > GAP_MS) {
        x.push((elapsedMs[i - 1] + 1) / 1000);
        y.push(null);
      }
      x.push(elapsedMs[i] / 1000);
      y.push(Number.isFinite(values[i]) ? values[i] : null);
    }
    return { x, y, resolution: "raw" };
  }

  const buckets = Math.max(1, Math.floor(maxPoints / 2));
  const perBucket = count / buckets;
  for (let b = 0; b < buckets; b++) {
    const from = first + Math.floor(b * perBucket);
    const to = first + Math.floor((b + 1) * perBucket);
    let min = Infinity;
    let max = -Infinity;
    for (let i = from; i < to; i++) {
      const v = values[i];
      if (!Number.isFinite(v)) continue;
      if (v < min) min = v;
      if (v > max) max = v;
    }
    const t = elapsedMs[from] / 1000;
    if (min === Infinity) {
      x.push(t);
      y.push(null);
    } else {
      x.push(t, (elapsedMs[from] + (elapsedMs[to - 1] - elapsedMs[from]) / 2) / 1000);
      y.push(min, max);
    }
  }
  return { x, y, resolution: "envelope" };
}

/**
 * Device clock time for a point in the recording, e.g. "20:56:03".
 * The device writes local time with no time zone, so this does plain clock arithmetic
 * (via UTC getters, which never shift for DST) instead of converting zones.
 */
export function deviceClockTime(startLocal: string | null, elapsedSeconds: number): string | null {
  const m = startLocal ? /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})/.exec(startLocal) : null;
  if (!m) return null;
  const startMs = Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]);
  const t = new Date(startMs + elapsedSeconds * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(t.getUTCHours())}:${pad(t.getUTCMinutes())}:${pad(t.getUTCSeconds())}`;
}

/** 67.2 -> "1:07", 3723 -> "1:02:03" */
export function formatElapsed(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return h > 0 ? `${h}:${pad(m)}:${pad(sec)}` : `${m}:${pad(sec)}`;
}
