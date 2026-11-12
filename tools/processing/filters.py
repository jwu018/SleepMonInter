"""Step 2: clean the raw inductance and keep only the breathing band."""

from __future__ import annotations

import numpy as np
from scipy.ndimage import median_filter
from scipy.signal import butter, sosfiltfilt

#: Inductance the belt can physically report. The belt rests near 4-5 uH and the onboard
#: test coil near 24 uH; readings like 1970 uH are sensor glitches, not the belt.
VALID_RANGE_UH = (0.5, 100.0)


def remove_glitches(
    L_uH: np.ndarray,
    fs_hz: float,
    max_jump_uH: float = 0.5,
    window_s: float = 1.0,
    max_stuck_s: float = 0.5,
) -> np.ndarray:
    """Return a copy of `L_uH` with physically impossible readings replaced by NaN.

    Three checks:
    0. Stuck sensor: a working LDC1612 (28-bit counts) never repeats EXACTLY the same value
       for long. A run of identical readings longer than `max_stuck_s` means the sensor isn't
       updating, e.g. right after power-on (one bench file sat at 1970.216 uH for 61 s).
    1. Absolute: anything outside VALID_RANGE_UH can't be the belt.
    2. Relative: anything more than `max_jump_uH` away from the median of the surrounding
       `window_s` is a spike. A breath moves L by ~0.06 uH, so 0.5 uH is far outside breathing.

    Why a median? A median ignores a few extreme values in its window, so a 1-3 sample spike
    doesn't drag the reference toward it (an average would). And when the belt really shifts
    and STAYS at a new level, the median moves to the new level too, so real steps survive:
    only values that jump away and come back are removed.
    """
    x = np.asarray(L_uH, dtype=float).copy()
    _blank_stuck_runs(x, int(round(max_stuck_s * fs_hz)))
    low, high = VALID_RANGE_UH
    x[(x < low) | (x > high)] = np.nan

    finite = np.isfinite(x)
    if finite.sum() < 3:
        return x
    # median_filter can't skip NaN, so compute the reference on a copy with holes bridged.
    idx = np.arange(len(x))
    bridged = np.interp(idx, idx[finite], x[finite])
    size = max(3, int(round(window_s * fs_hz)) | 1)  # odd, so the window is centred
    reference = median_filter(bridged, size=size, mode="nearest")

    x[np.abs(x - reference) > max_jump_uH] = np.nan
    return x


def bandpass(
    x: np.ndarray,
    fs_hz: float,
    low_hz: float = 0.1,
    high_hz: float = 1.0,
    order: int = 2,
    min_run_s: float = 10.0,
) -> np.ndarray:
    """Keep only `low_hz`..`high_hz` (6-60 breaths/min) with a zero-phase Butterworth filter.

    - Butterworth: "maximally flat" inside the band, so every breathing rate keeps the same
      size (no rate is boosted or shrunk relative to another).
    - sosfiltfilt: runs the filter forward, then backward. Each pass delays the signal by
      the same amount in opposite directions, so the delays cancel: peaks stay at their true
      times (zero phase). The price is that it needs the whole recording, which we have.
      "sos" (second-order sections) keeps a very low cutoff numerically stable.
    - order 2 per pass; filtfilt doubles the steepness, giving an effective 4th-order roll-off.

    NaN stretches (long gaps) can't be filtered across, so each NaN-free run is filtered on
    its own. Runs shorter than `min_run_s` stay NaN: a 0.1 Hz filter needs several seconds
    of signal to settle (its slowest wave is 10 s long).
    """
    x = np.asarray(x, dtype=float)
    out = np.full_like(x, np.nan)
    sos = butter(order, [low_hz, high_hz], btype="bandpass", fs=fs_hz, output="sos")

    finite = np.isfinite(x)
    edges = np.diff(np.concatenate([[0], finite.astype(np.int8), [0]]))
    starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    for s, e in zip(starts, ends, strict=True):
        if (e - s) / fs_hz < min_run_s:
            continue
        run = x[s:e]
        # Subtracting the median first means the filter starts near zero, which shrinks the
        # wobble at the start and end of the run (the "edge effect").
        out[s:e] = sosfiltfilt(sos, run - np.median(run))
    return out


def _blank_stuck_runs(x: np.ndarray, max_len: int) -> None:
    """In place: NaN every run of identical consecutive values longer than `max_len`."""
    if len(x) < 2:
        return
    same = np.concatenate([[False], x[1:] == x[:-1]])  # True where equal to the previous sample
    # Run boundaries: a run starts wherever `same` is False.
    starts = np.flatnonzero(~same)
    ends = np.concatenate([starts[1:], [len(x)]])
    for s, e in zip(starts, ends, strict=True):
        if e - s > max_len:
            x[s:e] = np.nan
