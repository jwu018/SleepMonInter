"""Reduce a long signal to a few thousand points for plotting, without losing its shape.

A night at 12.5 Hz is about 350,000 points, far more than a chart has pixels. Taking every
Nth point would drop spikes and flatten breaths. LTTB (Largest Triangle Three Buckets) keeps
the points that matter visually:

1. Always keep the first and the last point.
2. Split the points in between into equal buckets, one per output point.
3. In each bucket keep the point that forms the largest triangle with (a) the point kept
   from the previous bucket and (b) the average of the next bucket. A big triangle means
   the point sticks out, so peaks, troughs and spikes survive.

The kept points are real samples, never averages, so nothing is invented.
"""

from __future__ import annotations

import numpy as np


def lttb_indices(x: np.ndarray, y: np.ndarray, n_out: int) -> np.ndarray:
    """Indices of the `n_out` points LTTB keeps from one gap-free run. Sorted, unique."""
    n = len(x)
    if n_out >= n or n_out < 3:
        return np.arange(n)
    # Bucket edges over the interior points 1 .. n-2. n > n_out makes every bucket non-empty.
    edges = np.linspace(1, n - 1, n_out - 1).astype(np.int64)
    kept = np.empty(n_out, dtype=np.int64)
    kept[0], kept[-1] = 0, n - 1
    a = 0  # index of the point kept from the previous bucket
    for i in range(n_out - 2):
        lo, hi = edges[i], edges[i + 1]
        next_hi = edges[i + 2] if i + 2 < len(edges) else n
        next_x, next_y = x[hi:next_hi].mean(), y[hi:next_hi].mean()
        # Twice the triangle area for every candidate in this bucket (the 1/2 does not matter).
        area = np.abs((x[a] - next_x) * (y[lo:hi] - y[a]) - (x[a] - x[lo:hi]) * (next_y - y[a]))
        a = lo + int(area.argmax())
        kept[i + 1] = a
    return kept


def downsample(
    t_ms: np.ndarray, values: np.ndarray, max_points: int
) -> tuple[list[float], list[float | None], bool]:
    """(times, values, was_reduced) with at most about `max_points` points.

    Data gaps (NaN) are kept as gaps: each gap-free run is reduced on its own and a single
    None is placed between runs, which makes the chart break its line there.
    """
    finite = np.isfinite(values)
    edges = np.diff(np.concatenate([[0], finite.astype(np.int8), [0]]))
    starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    n_finite = int(finite.sum())
    reduce = n_finite > max_points

    out_t: list[float] = []
    out_v: list[float | None] = []
    if starts.size and starts[0] > 0:  # the window begins inside a gap
        out_t.append(float(t_ms[0]))
        out_v.append(None)
    for k, (s, e) in enumerate(zip(starts, ends, strict=True)):
        x, y = t_ms[s:e], values[s:e]
        if reduce:
            # Each run gets a share of the points in proportion to its length.
            share = max(3, round(max_points * (e - s) / n_finite))
            keep = lttb_indices(x, y, share)
            x, y = x[keep], y[keep]
        out_t.extend(x.tolist())
        out_v.extend(y.tolist())
        if e < len(values) and (k + 1 < len(starts) or e < len(values)):
            out_t.append(float(t_ms[e]))  # first missing sample after this run
            out_v.append(None)
    if not starts.size and len(values):  # the whole window is a gap
        out_t.append(float(t_ms[0]))
        out_v.append(None)
    return out_t, out_v, reduce
