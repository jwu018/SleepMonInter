"""Step 3: find each breath in the filtered signal."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import find_peaks


@dataclass
class Breaths:
    #: Sample index of each inhale peak (the turning point at the end of breathing in).
    peak_idx: np.ndarray
    #: Sample index of each exhale trough (the turning point at the end of breathing out).
    trough_idx: np.ndarray

    def peak_times_s(self, fs_hz: float) -> np.ndarray:
        return self.peak_idx / fs_hz

    def trough_times_s(self, fs_hz: float) -> np.ndarray:
        return self.trough_idx / fs_hz


def detect_breaths(
    x_filt: np.ndarray,
    fs_hz: float,
    min_period_s: float = 1.5,
    min_prominence: float | None = None,
    prominence_fraction: float = 0.2,
) -> Breaths:
    """Find inhale peaks and exhale troughs, alternating trough, peak, trough, peak...

    1. Prominence: how far a peak stands above the valleys on either side. Noise wiggles
       have tiny prominence; breaths have large prominence. If not given, the threshold is
       `prominence_fraction` of the typical breath size (5th-95th percentile spread), so it
       adapts to deep and shallow breathers alike while ignoring noise during a breath hold.
    2. Refractory period: two peaks closer than `min_period_s` (1.5 s = 40 breaths/min) are
       one breath with a wobble, so `distance` keeps only the bigger one.
    3. Peaks on x are one kind of turning point; peaks on -x (troughs) are the other.
    4. Alternation: real breathing alternates. If two peaks occur with no trough between
       them, keep the higher one; two troughs in a row, keep the lower one.

    Which way is "inhale" doesn't change the count. On our belt the sign still needs
    checking on the plots; amplitude and pause timing use whichever we call "peak".
    """
    x = np.asarray(x_filt, dtype=float)
    valid = np.isfinite(x)
    if valid.sum() < 3:
        return Breaths(np.array([], dtype=np.int64), np.array([], dtype=np.int64))

    if min_prominence is None:
        spread = np.nanpercentile(x, 95) - np.nanpercentile(x, 5)
        min_prominence = prominence_fraction * spread

    filled = np.where(valid, x, 0.0)  # find_peaks can't handle NaN
    distance = max(1, int(round(min_period_s * fs_hz)))
    peaks, _ = find_peaks(filled, distance=distance, prominence=min_prominence)
    troughs, _ = find_peaks(-filled, distance=distance, prominence=min_prominence)

    # Drop turning points in or touching a NaN stretch (they'd be artifacts of the zero fill).
    near_gap = ~valid | ~np.roll(valid, 1) | ~np.roll(valid, -1)
    peaks = peaks[~near_gap[peaks]]
    troughs = troughs[~near_gap[troughs]]

    return _alternate(x, peaks, troughs)


def _alternate(x: np.ndarray, peaks: np.ndarray, troughs: np.ndarray) -> Breaths:
    """Merge peaks and troughs in time order, so they strictly alternate."""
    events = sorted([(int(i), +1) for i in peaks] + [(int(i), -1) for i in troughs])
    kept: list[tuple[int, int]] = []
    for idx, kind in events:
        if kept and kept[-1][1] == kind:
            prev = kept[-1][0]
            # Same kind twice: keep the more extreme one.
            better = x[idx] > x[prev] if kind == +1 else x[idx] < x[prev]
            if better:
                kept[-1] = (idx, kind)
            continue
        kept.append((idx, kind))
    return Breaths(
        peak_idx=np.array([i for i, k in kept if k == +1], dtype=np.int64),
        trough_idx=np.array([i for i, k in kept if k == -1], dtype=np.int64),
    )
