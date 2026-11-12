// TypeScript versions of the numpy/scipy building blocks used by tools/processing.
// Each one follows scipy's algorithm step by step, so the web app gets the SAME breaths as
// the Python pipeline (checked by processing.test.mts against a Python-generated fixture).
// No imports: runs in the browser, the Web Worker and under `node --test`.

/** np.median of the finite values (NaN if none). */
export function median(values: ArrayLike<number>): number {
  const v = Array.from(values).filter(Number.isFinite).sort((a, b) => a - b);
  if (v.length === 0) return NaN;
  const mid = v.length >> 1;
  return v.length % 2 ? v[mid] : (v[mid - 1] + v[mid]) / 2;
}

/** np.nanpercentile with numpy's default "linear" method. */
export function nanPercentile(values: ArrayLike<number>, p: number): number {
  const v = Array.from(values).filter(Number.isFinite).sort((a, b) => a - b);
  if (v.length === 0) return NaN;
  const pos = (p / 100) * (v.length - 1);
  const lo = Math.floor(pos);
  const hi = Math.min(lo + 1, v.length - 1);
  return v[lo] + (v[hi] - v[lo]) * (pos - lo);
}

/** np.interp over indices: fill NaN by straight lines between finite neighbours (edges clamp). */
export function interpolateNaN(x: Float64Array): Float64Array {
  const out = new Float64Array(x);
  let prev = -1; // last finite index
  for (let i = 0; i < out.length; i++) {
    if (!Number.isFinite(out[i])) continue;
    if (prev === -1) {
      for (let j = 0; j < i; j++) out[j] = out[i]; // leading NaN: clamp to first value
    } else if (i - prev > 1) {
      for (let j = prev + 1; j < i; j++) out[j] = out[prev] + ((out[i] - out[prev]) * (j - prev)) / (i - prev);
    }
    prev = i;
  }
  if (prev !== -1) for (let j = prev + 1; j < out.length; j++) out[j] = out[prev]; // trailing
  return out;
}

/** scipy.ndimage.median_filter(x, size, mode="nearest") for odd `size`. */
export function medianFilterNearest(x: Float64Array, size: number): Float64Array {
  const half = size >> 1;
  const n = x.length;
  const out = new Float64Array(n);
  const window = new Float64Array(size);
  for (let i = 0; i < n; i++) {
    for (let k = -half; k <= half; k++) window[k + half] = x[Math.min(n - 1, Math.max(0, i + k))];
    window.sort();
    out[i] = window[half];
  }
  return out;
}

/** scipy.signal.sosfilt with initial state `zi` (direct form II transposed). */
function sosfilt(sos: number[][], x: Float64Array, zi: number[][]): Float64Array {
  const y = new Float64Array(x);
  for (let s = 0; s < sos.length; s++) {
    const [b0, b1, b2, , a1, a2] = sos[s];
    let z0 = zi[s][0];
    let z1 = zi[s][1];
    for (let i = 0; i < y.length; i++) {
      const xi = y[i];
      const yi = b0 * xi + z0;
      z0 = b1 * xi - a1 * yi + z1;
      z1 = b2 * xi - a2 * yi;
      y[i] = yi;
    }
  }
  return y;
}

/**
 * scipy.signal.sosfiltfilt(sos, x) with its defaults: odd extension of 3 * ntaps samples at
 * each end, steady-state initial conditions, forward pass, then backward pass.
 */
export function sosfiltfilt(sos: number[][], zi: number[][], x: Float64Array): Float64Array {
  let ntaps = 2 * sos.length + 1;
  ntaps -= Math.min(sos.filter((r) => r[2] === 0).length, sos.filter((r) => r[5] === 0).length);
  const edge = 3 * ntaps;
  if (x.length <= edge) throw new Error("signal too short to filter");

  // Odd extension: reflect the ends through the end values.
  const n = x.length;
  const ext = new Float64Array(n + 2 * edge);
  for (let i = 0; i < edge; i++) ext[i] = 2 * x[0] - x[edge - i];
  ext.set(x, edge);
  for (let i = 0; i < edge; i++) ext[edge + n + i] = 2 * x[n - 1] - x[n - 2 - i];

  const scaled = (v: number) => zi.map(([a, b]) => [a * v, b * v]);
  const forward = sosfilt(sos, ext, scaled(ext[0]));
  forward.reverse();
  const backward = sosfilt(sos, forward, scaled(forward[0]));
  backward.reverse();
  return backward.slice(edge, edge + n);
}

/** scipy.signal._peak_finding_utils._local_maxima_1d: local maxima, flat tops by their middle. */
function localMaxima(x: Float64Array): number[] {
  const peaks: number[] = [];
  let i = 1;
  const iMax = x.length - 1;
  while (i < iMax) {
    if (x[i - 1] < x[i]) {
      let ahead = i + 1;
      while (ahead < iMax && x[ahead] === x[i]) ahead++;
      if (x[ahead] < x[i]) {
        peaks.push((i + ahead - 1) >> 1);
        i = ahead;
      }
    }
    i++;
  }
  return peaks;
}

/** scipy's _select_by_peak_distance: keep higher peaks, drop neighbours closer than distance. */
function selectByDistance(peaks: number[], x: Float64Array, distance: number): number[] {
  const keep = new Array(peaks.length).fill(true);
  const order = peaks.map((_, i) => i).sort((a, b) => x[peaks[a]] - x[peaks[b]]); // low -> high
  const d = Math.ceil(distance);
  for (let r = order.length - 1; r >= 0; r--) {
    const j = order[r];
    if (!keep[j]) continue;
    for (let k = j - 1; k >= 0 && peaks[j] - peaks[k] < d; k--) keep[k] = false;
    for (let k = j + 1; k < peaks.length && peaks[k] - peaks[j] < d; k++) keep[k] = false;
  }
  return peaks.filter((_, i) => keep[i]);
}

/** scipy.signal.peak_prominences with no window limit. */
function prominence(x: Float64Array, peak: number): number {
  const h = x[peak];
  let leftMin = h;
  for (let i = peak; i >= 0 && x[i] <= h; i--) if (x[i] < leftMin) leftMin = x[i];
  let rightMin = h;
  for (let i = peak; i < x.length && x[i] <= h; i++) if (x[i] < rightMin) rightMin = x[i];
  return h - Math.max(leftMin, rightMin);
}

/** scipy.signal.find_peaks(x, distance=..., prominence=min) in the same order scipy applies them. */
export function findPeaks(x: Float64Array, distance: number, minProminence: number): number[] {
  let peaks = localMaxima(x);
  if (distance > 1) peaks = selectByDistance(peaks, x, distance);
  return peaks.filter((p) => prominence(x, p) >= minProminence);
}
