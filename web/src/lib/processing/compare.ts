// Helpers for overlaying several uploaded recordings. No imports beyond types, so they run
// under `node --test`.

import type { Breaths } from "./breathing.ts";

export interface XY {
  x: number[];
  y: (number | null)[];
}

/**
 * Breath-by-breath rate: 60 / (time between consecutive exhale troughs), plotted at the
 * second trough. For a 3-minute trial this gives ~50 points instead of 2-3 per-minute values.
 */
export function breathByBreathRate(breaths: Breaths, fs: number, offsetS = 0): XY {
  const t = breaths.trough_idx.map((i) => i / fs);
  const x: number[] = [];
  const y: number[] = [];
  for (let k = 1; k < t.length; k++) {
    x.push(offsetS + t[k]);
    y.push(60 / (t[k] - t[k - 1]));
  }
  return { x, y };
}

/**
 * Typical breath depth (median of peak minus the trough before it). Dividing a recording's
 * filtered signal by this puts different belt fits on the same scale: a normal breath ~ 1.
 */
export function medianBreathDepth(filtered: Float64Array, breaths: Breaths): number {
  const depths: number[] = [];
  let ti = 0;
  for (const p of breaths.peak_idx) {
    while (ti + 1 < breaths.trough_idx.length && breaths.trough_idx[ti + 1] < p) ti++;
    const t = breaths.trough_idx[ti];
    if (t !== undefined && t < p) depths.push(filtered[p] - filtered[t]);
  }
  if (depths.length === 0) return NaN;
  depths.sort((a, b) => a - b);
  const mid = depths.length >> 1;
  return depths.length % 2 ? depths[mid] : (depths[mid - 1] + depths[mid]) / 2;
}

/**
 * Put several series with different x values on one shared x axis (uPlot needs that).
 * Each series gets null where it has no point; draw with spanGaps so lines stay connected.
 */
export function alignSeries(series: XY[]): { x: number[]; ys: (number | null)[][] } {
  const xs = Array.from(new Set(series.flatMap((s) => s.x))).sort((a, b) => a - b);
  const position = new Map(xs.map((v, i) => [v, i]));
  const ys = series.map((s) => {
    const y: (number | null)[] = new Array(xs.length).fill(null);
    s.x.forEach((v, i) => {
      y[position.get(v)!] = s.y[i];
    });
    return y;
  });
  return { x: xs, ys };
}

/** Seconds after the noon before a device-clock start ("YYYY-MM-DD HH:MM:SS"), or null. */
export function deviceStartAfterNoonS(startLocal: string | null): number | null {
  const m = startLocal ? /^\d{4}-\d{2}-\d{2}[ T](\d{2}):(\d{2}):(\d{2})/.exec(startLocal) : null;
  if (!m) return null;
  const s = Number(m[1]) * 3600 + Number(m[2]) * 60 + Number(m[3]);
  return s < 12 * 3600 ? s + 12 * 3600 : s - 12 * 3600;
}
