"""Step 4: turn breaths into the numbers the dashboard and the tests report."""

from __future__ import annotations

import numpy as np

from .breaths import Breaths

MIN_MINUTE_COVERAGE_S = 30.0  # a minute needs this much breathing span to get a rate


def percent_error(calculated: float, counted: float) -> float:
    """Technical Memo 3, Appendix B: 100 * |calculated - counted| / counted."""
    if counted == 0:
        raise ValueError("counted is 0: percent error is undefined")
    return 100.0 * abs(calculated - counted) / counted


def count_complete_breaths(breaths: Breaths, n_samples: int) -> int:
    """Number of COMPLETE breaths: a peak with a trough before it AND a trough after it.

    A breath runs trough -> peak -> trough: breathing in up to the peak, out down to the next
    trough. So a peak only counts when both its inhale (the trough before) and its exhale
    (the trough after) are inside the file. This is the same rule the hand counters use, so
    a half breath at switch-on or switch-off is ignored by both.
    """
    p, t = breaths.peak_idx, breaths.trough_idx
    if len(p) == 0 or len(t) < 2:
        return 0
    # Peaks strictly between the first and the last trough each have a trough on both sides
    # (the peaks and troughs alternate, see breaths._alternate).
    return int(np.count_nonzero((p > t[0]) & (p < t[-1])))


def _breath_count_at(times_s: np.ndarray, trough_s: np.ndarray) -> np.ndarray:
    """Continuous "breaths so far" at each time: 0 at the first trough, 1 at the second...

    Between troughs it rises linearly, so half-way through a breath counts as half a breath.
    This mirrors how the synthetic ground truth counts (fractional breaths), which is fairer
    than counting whole peaks per minute.
    """
    return np.interp(times_s, trough_s, np.arange(len(trough_s), dtype=float))


def respiratory_rate_per_minute(breaths: Breaths, fs_hz: float, n_samples: int) -> np.ndarray:
    """Breaths per minute for each whole minute; NaN where it can't be measured.

    Minute k covers [60k, 60(k+1)) s. The rate is the fractional breath count across the
    part of the minute that lies between the first and last detected trough, scaled to 60 s.
    Minutes with less than 30 s inside that span (start/end of the recording) are NaN.
    A breath hold inside a minute correctly lowers that minute's rate.
    """
    n_minutes = int(n_samples // (60 * fs_hz))
    out = np.full(n_minutes, np.nan)
    trough_s = breaths.trough_times_s(fs_hz)
    if len(trough_s) < 2:
        return out
    first, last = trough_s[0], trough_s[-1]
    for k in range(n_minutes):
        a, b = max(60.0 * k, first), min(60.0 * (k + 1), last)
        if b - a < MIN_MINUTE_COVERAGE_S:
            continue
        cycles = _breath_count_at(np.array([a, b]), trough_s)
        out[k] = (cycles[1] - cycles[0]) / (b - a) * 60.0
    return out


def relative_amplitude(x_filt: np.ndarray, breaths: Breaths) -> np.ndarray:
    """Depth of each breath (peak minus the trough before it) divided by the median depth.

    1.0 = a typical breath for this person in this recording; 0.5 = half as deep. NOT a
    volume (that would need calibration). One value per peak that has a trough before it.
    """
    p, t = breaths.peak_idx, breaths.trough_idx
    if len(p) == 0 or len(t) == 0:
        return np.array([])
    before = np.searchsorted(t, p) - 1  # index of the trough just before each peak
    has_trough = before >= 0
    depth = x_filt[p[has_trough]] - x_filt[t[before[has_trough]]]
    median = np.median(depth)
    return depth / median if median > 0 else np.full_like(depth, np.nan)


def find_pauses(
    breaths: Breaths, fs_hz: float, min_pause_s: float = 10.0
) -> list[tuple[float, float]]:
    """(start_s, end_s) of every stretch longer than `min_pause_s` with no breathing.

    During normal breathing a turning point (peak or trough) comes every ~1-3 s. A breath
    hold is a long stretch with none: from the last turning point before it to the first one
    after it. Descriptive only: label these "breathing pause > 10 s", never a diagnosis.
    """
    turning = np.sort(np.concatenate([breaths.peak_idx, breaths.trough_idx])) / fs_hz
    gaps = np.diff(turning)
    return [(float(turning[i]), float(turning[i + 1])) for i in np.flatnonzero(gaps > min_pause_s)]
