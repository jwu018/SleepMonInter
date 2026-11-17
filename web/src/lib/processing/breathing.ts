// The breathing algorithm (TypeScript copy of tools/processing). Runs on uploaded recordings.
// Python is the reference: see tools/processing/*.py for the reasoning behind every step.
// If you change the algorithm there, change it here and rerun tools/export_web_processing.py
// (the cross-check test then confirms both still agree).

import type { DeviceRecording } from "../device/parseDeviceCsv.ts";
import {
  findPeaks,
  interpolateNaN,
  median,
  medianFilterNearest,
  nanPercentile,
  sosfiltfilt,
} from "./dsp.ts";
import { BAND_HZ, BANDPASS, type Coefficients, HIGHPASS, LOWPASS } from "./filterCoefficients.ts";

const VALID_RANGE_UH = [0.5, 100] as const;
const MAX_JUMP_UH = 0.5;
const MAX_STUCK_S = 0.5;
const MAX_GAP_S = 2.0;
const MIN_RUN_S = 10.0;
const MIN_PERIOD_S = 1.0;
const PROMINENCE_FRACTION = 0.15;
const MIN_MINUTE_COVERAGE_S = 30.0;
export const PAUSE_S = 10.0;
export const PAUSE_WINDOW_S = 3.0; // movement is judged inside this window
export const PAUSE_STILL_FRACTION = 0.2; // "still" = moves less than 20% of a typical breath
const PAUSE_SMOOTH_S = 0.4; // average this long first, so sensor noise isn't movement
// Signal quality (quality.py): starting thresholds, to be tuned on the Test 2 recordings.
export const GOOD_SNR_DB = 15.0;
export const GOOD_SIR_DB = 10.0;
const QUALITY_WINDOW_S = 60.0;
const MIN_SIR_WINDOW_S = 30.0;
const MAX_MISSING_FRACTION = 0.5;

// --- load.py: put samples on an even grid by their scheduled sample index ------------------

/**
 * The settings above in words, for the "How this recording was processed" list on the upload
 * page. Built from the constants so the page can't drift from the code. The reasons and the
 * measurements behind them are in docs/FILTERING.md.
 */
export const PROCESSING_SETTINGS: { step: string; setting: string; effect: string }[] = [
  {
    step: "Reject impossible readings",
    setting: `outside ${VALID_RANGE_UH[0]}–${VALID_RANGE_UH[1]} µH, repeated exactly for over ${MAX_STUCK_S} s, or more than ${MAX_JUMP_UH} µH from the 1 s median`,
    effect: "Rejected readings become gaps and are counted in “Readings removed”. A breath is about 0.06 µH, so breathing is never rejected.",
  },
  {
    step: "Bridge short gaps",
    setting: `straight line across gaps of ${MAX_GAP_S} s or less`,
    effect: "Longer gaps stay as visible gaps. Nothing is invented across them.",
  },
  {
    step: "Band-pass filter",
    setting: `${BAND_HZ[0]}–${BAND_HZ[1]} Hz (${Math.round(BAND_HZ[0] * 60)}–${Math.round(BAND_HZ[1] * 60)} breaths/min), run forward and backward`,
    effect: "Removes slow drift and fast sensor noise. Keeps at least 95% of breath depth from 10 to 36 breaths/min. Does not shift breaths in time.",
  },
  {
    step: "Find breaths",
    setting: `peaks at least ${MIN_PERIOD_S} s apart that stand out by ${Math.round(PROMINENCE_FRACTION * 100)}% of the typical breath size`,
    effect: `Measures up to about 55 breaths/min (hard limit ${Math.round(60 / MIN_PERIOD_S)}). Some breaths shallower than about 35% of normal are missed. Movement can add fake breaths in minutes marked poor.`,
  },
  {
    step: "Find pauses",
    setting: `chest moves less than ${Math.round(PAUSE_STILL_FRACTION * 100)}% of a typical breath for more than ${PAUSE_S} s`,
    effect: "Measured on the cleaned signal, not the filtered one, because the filter distorts a flat line.",
  },
];

export interface Grid {
  fs_hz: number;
  L_uH: Float64Array; // NaN where a sample was lost or blank
}

export function toGrid(rec: DeviceRecording): Grid {
  const fs = rec.meta.sample_rate_hz ?? 25;
  const sample = rec.columns.sample;
  const n = sample.length ? sample[sample.length - 1] - sample[0] + 1 : 0;
  const L = new Float64Array(n).fill(NaN);
  for (let i = 0; i < sample.length; i++) L[sample[i] - sample[0]] = rec.columns.ldc_L_uH[i];
  return { fs_hz: fs, L_uH: L };
}

/** load.fill_short_gaps */
export function fillShortGaps(x: Float64Array, fs: number, maxGapS = MAX_GAP_S): Float64Array {
  const y = new Float64Array(x);
  const maxLen = Math.round(maxGapS * fs);
  let i = 0;
  while (i < y.length) {
    if (Number.isFinite(y[i])) {
      i++;
      continue;
    }
    const s = i;
    while (i < y.length && !Number.isFinite(y[i])) i++;
    const e = i; // NaN run [s, e)
    if (e - s <= maxLen && s > 0 && e < y.length) {
      for (let j = s; j < e; j++) y[j] = y[s - 1] + ((y[e] - y[s - 1]) * (j - s + 1)) / (e - s + 1);
    }
  }
  return y;
}

// --- filters.py -----------------------------------------------------------------------------

export function removeGlitches(L: Float64Array, fs: number): Float64Array {
  const x = new Float64Array(L);
  // 0. Stuck sensor: identical consecutive readings for longer than MAX_STUCK_S.
  const maxLen = Math.round(MAX_STUCK_S * fs);
  let runStart = 0;
  for (let i = 1; i <= x.length; i++) {
    if (i < x.length && x[i] === x[i - 1]) continue;
    if (i - runStart > maxLen) x.fill(NaN, runStart, i);
    runStart = i;
  }
  // 1. Absolute range.
  for (let i = 0; i < x.length; i++) if (x[i] < VALID_RANGE_UH[0] || x[i] > VALID_RANGE_UH[1]) x[i] = NaN;
  // 2. Far from the 1 s rolling median.
  let finite = 0;
  for (const v of x) if (Number.isFinite(v)) finite++;
  if (finite < 3) return x;
  const size = Math.max(3, Math.round(fs) | 1);
  const reference = medianFilterNearest(interpolateNaN(x), size);
  for (let i = 0; i < x.length; i++) if (Math.abs(x[i] - reference[i]) > MAX_JUMP_UH) x[i] = NaN;
  return x;
}

export function bandpass(x: Float64Array, fs: number): Float64Array {
  return filterRuns(x, fs, BANDPASS);
}

/** sosfiltfilt each NaN-free run of at least MIN_RUN_S on its own (median removed first). */
function filterRuns(x: Float64Array, fs: number, table: Coefficients): Float64Array {
  const coef = table[String(fs)];
  if (!coef) throw new Error(`No filter for ${fs} Hz. Add it in tools/export_web_processing.py.`);
  const out = new Float64Array(x.length).fill(NaN);
  let i = 0;
  while (i < x.length) {
    if (!Number.isFinite(x[i])) {
      i++;
      continue;
    }
    const s = i;
    while (i < x.length && Number.isFinite(x[i])) i++;
    if ((i - s) / fs < MIN_RUN_S) continue;
    const run = x.slice(s, i);
    const m = median(run);
    out.set(sosfiltfilt(coef.sos, coef.zi, run.map((v) => v - m)), s);
  }
  return out;
}

// --- quality.py: SNR, SIR, per-minute flags --------------------------------------------------

export interface Bands {
  breathing: Float64Array; // 0.1-1 Hz
  noise: Float64Array; // above 1 Hz
  interference: Float64Array; // below 0.1 Hz
}

export interface WindowQuality {
  start_s: number;
  snr_db: number;
  sir_db: number;
  label: "good" | "poor" | "no_signal";
}

const db = (signal: number, other: number) =>
  !Number.isFinite(signal) || !Number.isFinite(other) || other <= 0
    ? NaN
    : signal <= 0
      ? -Infinity
      : 10 * Math.log10(signal / other);

/** Population variance of the values at indices where `ok` is true (np.var). */
function variance(x: Float64Array, ok: boolean[], start: number): number {
  let n = 0;
  let sum = 0;
  for (let i = 0; i < ok.length; i++) if (ok[i]) { sum += x[start + i]; n++; }
  const mean = sum / n;
  let ss = 0;
  for (let i = 0; i < ok.length; i++) if (ok[i]) ss += (x[start + i] - mean) ** 2;
  return ss / n;
}

/** (SNR, SIR) in dB for samples [start, end). SIR is NaN for windows shorter than 30 s. */
export function snrSirDb(bands: Bands, start: number, end: number, fs: number): [number, number] {
  const ok: boolean[] = [];
  for (let i = start; i < end; i++) {
    ok.push(Number.isFinite(bands.breathing[i]) && Number.isFinite(bands.noise[i]) && Number.isFinite(bands.interference[i]));
  }
  if (ok.filter(Boolean).length < 2) return [NaN, NaN];
  const b = variance(bands.breathing, ok, start);
  const snr = db(b, variance(bands.noise, ok, start));
  const sir = (end - start) / fs >= MIN_SIR_WINDOW_S ? db(b, variance(bands.interference, ok, start)) : NaN;
  return [snr, sir];
}

/** Per-minute good / poor / no_signal. `deglitched` is before gap filling (rejected = missing). */
export function windowQuality(deglitched: Float64Array, bands: Bands, fs: number): WindowQuality[] {
  const size = Math.round(QUALITY_WINDOW_S * fs);
  const out: WindowQuality[] = [];
  for (let k = 0; k < Math.floor(deglitched.length / size); k++) {
    const s = k * size;
    const e = s + size;
    let finite = 0;
    for (let i = s; i < e; i++) if (Number.isFinite(deglitched[i])) finite++;
    const missing = 1 - finite / size;
    const [snr, sir] = snrSirDb(bands, s, e, fs);
    const label =
      missing > MAX_MISSING_FRACTION || !Number.isFinite(snr)
        ? "no_signal"
        : snr >= GOOD_SNR_DB && (!Number.isFinite(sir) || sir >= GOOD_SIR_DB)
          ? "good"
          : "poor";
    out.push({ start_s: k * QUALITY_WINDOW_S, snr_db: snr, sir_db: sir, label });
  }
  return out;
}

// --- breaths.py -----------------------------------------------------------------------------

export interface Breaths {
  peak_idx: number[];
  trough_idx: number[];
}

export function detectBreaths(x: Float64Array, fs: number): Breaths {
  const valid = Array.from(x, Number.isFinite);
  if (valid.filter(Boolean).length < 3) return { peak_idx: [], trough_idx: [] };
  const minProm = PROMINENCE_FRACTION * (nanPercentile(x, 95) - nanPercentile(x, 5));
  const filled = x.map((v) => (Number.isFinite(v) ? v : 0));
  const distance = Math.max(1, Math.round(MIN_PERIOD_S * fs));
  const n = x.length;
  // np.roll wraps around, so index 0 checks the last sample and vice versa (same as Python).
  const nearGap = (i: number) => !valid[i] || !valid[(i - 1 + n) % n] || !valid[(i + 1) % n];
  const peaks = findPeaks(filled, distance, minProm).filter((i) => !nearGap(i));
  const troughs = findPeaks(filled.map((v) => -v), distance, minProm).filter((i) => !nearGap(i));
  return alternate(x, peaks, troughs);
}

function alternate(x: Float64Array, peaks: number[], troughs: number[]): Breaths {
  const events = [...peaks.map((i) => [i, 1] as const), ...troughs.map((i) => [i, -1] as const)].sort(
    (a, b) => a[0] - b[0] || a[1] - b[1],
  );
  const kept: [number, number][] = [];
  for (const [idx, kind] of events) {
    const last = kept[kept.length - 1];
    if (last && last[1] === kind) {
      const better = kind === 1 ? x[idx] > x[last[0]] : x[idx] < x[last[0]];
      if (better) kept[kept.length - 1] = [idx, kind];
      continue;
    }
    kept.push([idx, kind]);
  }
  return {
    peak_idx: kept.filter(([, k]) => k === 1).map(([i]) => i),
    trough_idx: kept.filter(([, k]) => k === -1).map(([i]) => i),
  };
}

// --- metrics.py + pipeline.py -----------------------------------------------------------------

/** Complete breaths (a peak with a trough on each side) inside [startS, endS]. */
export function countCompleteBreaths(b: Breaths, fs: number, startS: number, endS: number): number {
  const inside = (i: number) => i / fs >= startS && i / fs <= endS;
  const p = b.peak_idx.filter(inside);
  const t = b.trough_idx.filter(inside);
  if (p.length === 0 || t.length < 2) return 0;
  return p.filter((i) => i > t[0] && i < t[t.length - 1]).length;
}

export function ratePerMinute(b: Breaths, fs: number, nSamples: number): (number | null)[] {
  const nMinutes = Math.floor(nSamples / (60 * fs));
  const ts = b.trough_idx.map((i) => i / fs);
  const out: (number | null)[] = new Array(nMinutes).fill(null);
  if (ts.length < 2) return out;
  const cyclesAt = (t: number) => {
    let k = 0;
    while (k < ts.length - 2 && ts[k + 1] < t) k++;
    return k + (t - ts[k]) / (ts[k + 1] - ts[k]);
  };
  for (let m = 0; m < nMinutes; m++) {
    const a = Math.max(60 * m, ts[0]);
    const z = Math.min(60 * (m + 1), ts[ts.length - 1]);
    if (z - a < MIN_MINUTE_COVERAGE_S) continue;
    out[m] = ((cyclesAt(z) - cyclesAt(a)) / (z - a)) * 60;
  }
  return out;
}

export function relativeAmplitude(x: Float64Array, b: Breaths): number[] {
  const depths: number[] = [];
  for (const p of b.peak_idx) {
    let before = -1;
    for (const t of b.trough_idx) if (t < p) before = t;
    if (before >= 0) depths.push(x[p] - x[before]);
  }
  const m = median(depths);
  return depths.map((d) => (m > 0 ? d / m : NaN));
}

/** Typical breath size: the median of (peak minus the trough before it). NaN if no breaths. */
export function medianBreathDepth(x: Float64Array, b: Breaths): number {
  const depths: number[] = [];
  for (const p of b.peak_idx) {
    let before = -1;
    for (const t of b.trough_idx) if (t < p) before = t;
    if (before >= 0) depths.push(x[p] - x[before]);
  }
  return depths.length ? median(depths) : NaN;
}

/** Centred moving window over x with the edges repeated (scipy's mode="nearest"). */
function rolling(x: Float64Array, size: number, combine: (window: Float64Array) => number): Float64Array {
  const half = size >> 1;
  const n = x.length;
  const out = new Float64Array(n);
  const window = new Float64Array(size);
  for (let i = 0; i < n; i++) {
    for (let k = 0; k < size; k++) window[k] = x[Math.min(n - 1, Math.max(0, i - half + k))];
    out[i] = combine(window);
  }
  return out;
}

/**
 * Stretches longer than `minPauseS` where the chest barely moves: within any 3 s the signal
 * changes by less than 20% of a typical breath.
 *
 * This reads the CLEANED signal, not the band-passed one. The band-pass removes everything
 * slower than 0.1 Hz, and a breath hold is slow: the filter bends the flat line into a low
 * hump with a fake peak, which hid most 11-15 s pauses from the old turning-point rule.
 * Same steps as find_pauses in tools/processing/metrics.py.
 */
export function findPauses(
  cleaned: Float64Array,
  typicalDepth: number,
  fs: number,
  minPauseS = PAUSE_S,
): [number, number][] {
  const n = cleaned.length;
  let finiteCount = 0;
  for (let i = 0; i < n; i++) if (Number.isFinite(cleaned[i])) finiteCount++;
  if (!Number.isFinite(typicalDepth) || typicalDepth <= 0 || finiteCount < 3) return [];

  const size = Math.max(3, Math.round(PAUSE_WINDOW_S * fs) | 1);
  const smoothN = Math.max(1, Math.round(PAUSE_SMOOTH_S * fs) | 1);
  const halfS = (size >> 1) / fs;

  const smooth = rolling(interpolateNaN(cleaned), smoothN, (w) => {
    let sum = 0;
    for (const v of w) sum += v;
    return sum / w.length;
  });
  const movement = rolling(smooth, size, (w) => {
    let lo = Infinity;
    let hi = -Infinity;
    for (const v of w) {
      if (v < lo) lo = v;
      if (v > hi) hi = v;
    }
    return hi - lo;
  });
  const missing = new Float64Array(n);
  for (let i = 0; i < n; i++) missing[i] = Number.isFinite(cleaned[i]) ? 0 : 1;
  const hasGap = rolling(missing, size, (w) => {
    for (const v of w) if (v > 0) return 1;
    return 0;
  });

  const out: [number, number][] = [];
  let runStart = -1;
  for (let i = 0; i <= n; i++) {
    const still = i < n && movement[i] < PAUSE_STILL_FRACTION * typicalDepth && hasGap[i] === 0;
    if (still && runStart < 0) runStart = i;
    if (!still && runStart >= 0) {
      // A window that still touches the last breath isn't "still", so add half a window back.
      const startS = Math.max(0, runStart / fs - halfS);
      const endS = Math.min((n - 1) / fs, (i - 1) / fs + halfS);
      if (endS - startS > minPauseS) out.push([startS, endS]);
      runStart = -1;
    }
  }
  return out;
}

export interface BreathingAnalysis {
  fs_hz: number;
  n_samples: number;
  /** Band-passed breathing signal on the even grid (index / fs_hz = seconds since start). */
  filtered: Float64Array;
  /**
   * What the band-pass took out: the cleaned signal (centred on its median) minus `filtered`.
   * Shown on request so nobody has to trust that only drift and noise were removed.
   */
  removed: Float64Array;
  breaths: Breaths;
  pauses: [number, number][];
  rate_per_minute: (number | null)[];
  /** Fraction of readings removed as stuck/out of range/spikes. */
  removed_fraction: number;
  /** The three frequency bands (breathing = `filtered`), for SNR/SIR over any window. */
  bands: Bands;
  /** Per-minute signal quality. */
  quality: WindowQuality[];
}

/** The whole pipeline on one uploaded recording, or null when there's no sensor data. */
export function analyzeRecording(rec: DeviceRecording): BreathingAnalysis | null {
  if (rec.stats.sensor_rows === 0) return null;
  const grid = toGrid(rec);
  const cleanedRaw = removeGlitches(grid.L_uH, grid.fs_hz);
  let kept = 0;
  let present = 0;
  for (let i = 0; i < grid.L_uH.length; i++) {
    if (Number.isFinite(grid.L_uH[i])) present++;
    if (Number.isFinite(cleanedRaw[i])) kept++;
  }
  const cleaned = fillShortGaps(cleanedRaw, grid.fs_hz);
  const filtered = bandpass(cleaned, grid.fs_hz);
  const breaths = detectBreaths(filtered, grid.fs_hz);
  const bands: Bands = {
    breathing: filtered,
    noise: filterRuns(cleaned, grid.fs_hz, HIGHPASS),
    interference: filterRuns(cleaned, grid.fs_hz, LOWPASS),
  };
  const finite = Array.from(cleaned).filter(Number.isFinite);
  const centre = finite.length ? median(finite) : 0;
  const removed = cleaned.map((v, i) => v - centre - filtered[i]); // NaN wherever either is NaN
  return {
    fs_hz: grid.fs_hz,
    n_samples: filtered.length,
    filtered,
    removed,
    breaths,
    pauses: findPauses(cleaned, medianBreathDepth(filtered, breaths), grid.fs_hz),
    rate_per_minute: ratePerMinute(breaths, grid.fs_hz, filtered.length),
    removed_fraction: present ? 1 - kept / present : 0,
    bands,
    quality: windowQuality(cleanedRaw, bands, grid.fs_hz),
  };
}
