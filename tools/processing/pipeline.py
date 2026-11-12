"""Run the whole chain on one trial."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .breaths import Breaths, detect_breaths
from .filters import bandpass, remove_glitches
from .load import Trial, fill_short_gaps
from .metrics import count_complete_breaths
from .quality import WindowQuality, snr_sir_db, split_bands, window_quality


@dataclass
class TrialResult:
    cleaned: np.ndarray  # glitches removed, short gaps bridged
    filtered: np.ndarray  # band-passed breathing signal
    breaths: Breaths  # every breath detected in the whole file
    #: The counting window, in seconds since switch-on (after trimming the settling time).
    window_s: tuple[float, float]
    breath_count: int  # complete breaths inside the window
    rate_bpm: float  # breath_count per minute of window
    snr_db: float  # breathing vs >1 Hz noise, over the counting window
    sir_db: float  # breathing vs <0.1 Hz drift/motion, over the counting window
    quality: list[WindowQuality]  # per minute: good / poor / no_signal


def breaths_in_window(breaths: Breaths, fs_hz: float, start_s: float, end_s: float) -> Breaths:
    """Only the peaks and troughs inside [start_s, end_s]."""

    def inside(idx: np.ndarray) -> np.ndarray:
        t = idx / fs_hz
        return idx[(t >= start_s) & (t <= end_s)]

    return Breaths(peak_idx=inside(breaths.peak_idx), trough_idx=inside(breaths.trough_idx))


def process_trial(
    trial: Trial,
    low_hz: float = 0.1,
    high_hz: float = 1.0,
    trim_start_s: float = 0.0,
    trim_end_s: float = 0.0,
) -> TrialResult:
    """Clean, filter, detect breaths, then count complete breaths inside the window.

    `trim_start_s` / `trim_end_s` skip the belt settling after switch-on and the handling
    before switch-off. The hand counters must count the SAME window (e.g. start counting
    10 s after switch-on), otherwise the comparison isn't like for like.
    """
    if not np.isfinite(trial.L_uH).any():
        raise ValueError("no sensor data in this file (the inductance columns are blank)")
    deglitched = remove_glitches(trial.L_uH, trial.fs_hz)
    cleaned = fill_short_gaps(deglitched, trial.fs_hz)
    filtered = bandpass(cleaned, trial.fs_hz, low_hz, high_hz)
    bands = split_bands(cleaned, trial.fs_hz)
    breaths = detect_breaths(filtered, trial.fs_hz)

    start, end = trim_start_s, trial.duration_s - trim_end_s
    if end - start <= 0:
        raise ValueError("the trims leave no time to count")
    count = count_complete_breaths(
        breaths_in_window(breaths, trial.fs_hz, start, end), len(filtered)
    )
    fs = trial.fs_hz
    snr, sir = snr_sir_db(bands, int(start * fs), int(end * fs), fs)
    return TrialResult(
        cleaned=cleaned,
        filtered=filtered,
        breaths=breaths,
        window_s=(start, end),
        breath_count=count,
        rate_bpm=count / ((end - start) / 60.0),
        snr_db=snr,
        sir_db=sir,
        quality=window_quality(deglitched, bands, fs),
    )
