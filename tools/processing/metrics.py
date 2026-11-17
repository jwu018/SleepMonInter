"""Step 4: turn breaths into the numbers the dashboard and the tests report."""

from __future__ import annotations

import numpy as np
from scipy.ndimage import maximum_filter1d, minimum_filter1d, uniform_filter1d

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


def amplitude_per_minute(
    filtered: np.ndarray, breaths: Breaths, fs_hz: float, n_minutes: int
) -> np.ndarray:
    """Mean relative depth of the breaths whose peak falls in each minute (NaN if none)."""
    p, t = breaths.peak_idx, breaths.trough_idx
    out = np.full(n_minutes, np.nan)
    if len(p) == 0 or len(t) == 0:
        return out
    has_trough = np.searchsorted(t, p) - 1 >= 0
    rel = relative_amplitude(filtered, breaths)  # one value per peak that has a trough before it
    minute = (p[has_trough] / fs_hz // 60).astype(np.int64)
    ok = minute < n_minutes
    total = np.bincount(minute[ok], weights=rel[ok], minlength=n_minutes)
    count = np.bincount(minute[ok], minlength=n_minutes)
    out[count > 0] = total[count > 0] / count[count > 0]
    return out


def median_breath_depth(x_filt: np.ndarray, breaths: Breaths) -> float:
    """The typical breath size: median of (peak minus the trough before it). NaN if no breaths."""
    p, t = breaths.peak_idx, breaths.trough_idx
    if len(p) == 0 or len(t) == 0:
        return float("nan")
    before = np.searchsorted(t, p) - 1
    has_trough = before >= 0
    if not has_trough.any():
        return float("nan")
    return float(np.median(x_filt[p[has_trough]] - x_filt[t[before[has_trough]]]))


def find_pauses(
    cleaned: np.ndarray,
    typical_depth: float,
    fs_hz: float,
    min_pause_s: float = 10.0,
    window_s: float = 3.0,
    still_fraction: float = 0.2,
    smooth_s: float = 0.4,
) -> list[tuple[float, float]]:
    """(start_s, end_s) of every stretch longer than `min_pause_s` where the chest barely moves.

    "Barely moves" = within any `window_s` the signal changes by less than `still_fraction`
    of a typical breath (`typical_depth`, from `median_breath_depth`).

    Why this looks at the CLEANED signal and not the band-passed one: the band-pass removes
    everything slower than 0.1 Hz, and a breath hold IS slow (a flat line for 10+ s). The
    filter bends that flat line back toward zero, which creates a low hump with a fake peak
    in the middle of the hold. Counting the gap between turning points of the filtered signal
    therefore missed most 11-15 s pauses (see docs/FILTERING.md). Movement inside a 3 s
    window needs no high-pass: drift is far too slow to matter over 3 s.

    Steps:
    1. Average over `smooth_s` so sensor noise doesn't count as movement.
    2. Movement at each sample = max - min of the smoothed signal in the surrounding window.
    3. A run of low movement is a pause. A window that still touches the last breath isn't
       "still", so each run is half a window short at both ends; add that back.

    Data gaps are not pauses: a window containing missing data is never "still".
    Descriptive only: label these "breathing pause > 10 s", never a diagnosis. A chest band
    can't see a pause where the child keeps trying to breathe against a blocked airway.
    """
    x = np.asarray(cleaned, dtype=float)
    finite = np.isfinite(x)
    if not np.isfinite(typical_depth) or typical_depth <= 0 or finite.sum() < 3:
        return []
    size = max(3, int(round(window_s * fs_hz)) | 1)  # odd, so the window is centred
    smooth_n = max(1, int(round(smooth_s * fs_hz)) | 1)
    half_s = (size // 2) / fs_hz

    idx = np.arange(len(x))
    bridged = np.interp(idx, idx[finite], x[finite])  # the filters below can't skip NaN
    smooth = uniform_filter1d(bridged, smooth_n, mode="nearest")
    movement = maximum_filter1d(smooth, size, mode="nearest") - minimum_filter1d(
        smooth, size, mode="nearest"
    )
    has_gap = maximum_filter1d((~finite).astype(np.int8), size, mode="nearest") > 0
    still = (movement < still_fraction * typical_depth) & ~has_gap

    edges = np.diff(np.concatenate([[0], still.astype(np.int8), [0]]))
    pauses = []
    for s, e in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1), strict=True):
        start_s = max(0.0, s / fs_hz - half_s)
        end_s = min((len(x) - 1) / fs_hz, (e - 1) / fs_hz + half_s)
        if end_s - start_s > min_pause_s:
            pauses.append((float(start_s), float(end_s)))
    return pauses
