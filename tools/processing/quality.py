"""Signal quality: SNR, SIR and per-minute good / poor / no_signal flags.

Three frequency bands of the cleaned inductance signal:

    interference   below 0.1 Hz   drift, posture shifts, slow movement
    breathing      0.1 - 1 Hz     6-60 breaths/min
    noise          above 1 Hz     sensor and electronic noise

    SNR (dB) = 10 log10(breathing power / noise power)
    SIR (dB) = 10 log10(breathing power / interference power)

Power in a band = the variance of the signal after filtering it to that band. (By Parseval's
theorem that equals the area under the power spectrum in that band, so this matches a
spectrum-based measurement, but it reuses the zero-phase filters we already have.)

Limit: movement AT breathing speed (~0.3 Hz) lands in the breathing band, so neither ratio
can see it. That needs another sensor or a breath-regularity check.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import butter, sosfiltfilt

from .filters import bandpass

BREATHING_HZ = (0.1, 1.0)
GOOD_SNR_DB = 15.0  # starting thresholds: tune on the Test 2 recordings
GOOD_SIR_DB = 10.0
WINDOW_S = 60.0  # quality is judged per minute, like the dashboard's trend charts
MIN_SIR_WINDOW_S = 30.0  # below 0.1 Hz needs >= ~3 cycles of 0.1 Hz to measure
MAX_MISSING_FRACTION = 0.5  # more missing than this -> no_signal


@dataclass
class Bands:
    breathing: np.ndarray
    noise: np.ndarray
    interference: np.ndarray


def _filter_runs(x: np.ndarray, sos: np.ndarray, min_len: int) -> np.ndarray:
    """sosfiltfilt each NaN-free run of x on its own (NaN stays NaN; short runs stay NaN)."""
    out = np.full_like(x, np.nan)
    finite = np.isfinite(x)
    edges = np.diff(np.concatenate([[0], finite.astype(np.int8), [0]]))
    for s, e in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1), strict=True):
        if e - s >= min_len:
            run = x[s:e]
            out[s:e] = sosfiltfilt(sos, run - np.median(run))
    return out


def split_bands(cleaned: np.ndarray, fs_hz: float) -> Bands:
    """Split the cleaned signal (glitches removed, short gaps bridged) into the three bands."""
    min_len = int(10 * fs_hz)
    low, high = BREATHING_HZ
    lp = butter(2, low, btype="lowpass", fs=fs_hz, output="sos")
    hp = butter(2, high, btype="highpass", fs=fs_hz, output="sos")
    return Bands(
        breathing=bandpass(cleaned, fs_hz, low, high),
        noise=_filter_runs(cleaned, hp, min_len),
        interference=_filter_runs(cleaned, lp, min_len),
    )


def _db(signal_power: float, other_power: float) -> float:
    if not (np.isfinite(signal_power) and np.isfinite(other_power)) or other_power <= 0:
        return float("nan")
    if signal_power <= 0:
        return float("-inf")
    return float(10 * np.log10(signal_power / other_power))


def snr_sir_db(bands: Bands, start: int, end: int, fs_hz: float) -> tuple[float, float]:
    """(SNR, SIR) in dB for samples [start, end). SIR is NaN for windows shorter than 30 s."""
    b, n, i = (arr[start:end] for arr in (bands.breathing, bands.noise, bands.interference))
    ok = np.isfinite(b) & np.isfinite(n) & np.isfinite(i)
    if ok.sum() < 2:
        return float("nan"), float("nan")
    snr = _db(np.var(b[ok]), np.var(n[ok]))
    sir = (
        _db(np.var(b[ok]), np.var(i[ok]))
        if (end - start) / fs_hz >= MIN_SIR_WINDOW_S
        else float("nan")
    )
    return snr, sir


@dataclass
class WindowQuality:
    start_s: float
    snr_db: float
    sir_db: float
    label: str  # "good" | "poor" | "no_signal"


def window_quality(
    raw_L_uH: np.ndarray, bands: Bands, fs_hz: float, window_s: float = WINDOW_S
) -> list[WindowQuality]:
    """Label each whole window: no_signal (mostly missing/rejected), poor, or good.

    `raw_L_uH` is the glitch-removed signal BEFORE gap filling, so rejected readings count
    as missing here.
    """
    size = int(round(window_s * fs_hz))
    out = []
    for k in range(len(raw_L_uH) // size):
        s, e = k * size, (k + 1) * size
        missing = 1 - np.isfinite(raw_L_uH[s:e]).mean()
        snr, sir = snr_sir_db(bands, s, e, fs_hz)
        if missing > MAX_MISSING_FRACTION or not np.isfinite(snr):
            label = "no_signal"
        elif snr >= GOOD_SNR_DB and (not np.isfinite(sir) or sir >= GOOD_SIR_DB):
            label = "good"
        else:
            label = "poor"
        out.append(WindowQuality(k * window_s, snr, sir, label))
    return out
