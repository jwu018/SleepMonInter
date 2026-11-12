"""Tests for tools/processing.

Scaffolding tests (loading, gap filling, Appendix B, the trial report) and algorithm tests
(glitches, band-pass, breath detection, counts, per-minute rate, amplitude, pauses), checked
against synthetic ground truth and the team's real belt recording.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

import trial_report
from generate_synthetic import INHALE_FRACTION, PROFILES, simulate_night, write_recording
from processing.breaths import Breaths
from processing.filters import bandpass, remove_glitches
from processing.load import fill_short_gaps, load_trial
from processing.metrics import (
    count_complete_breaths,
    find_pauses,
    percent_error,
    relative_amplitude,
    respiratory_rate_per_minute,
)
from processing.pipeline import process_trial

FS = 25.0
REAL_BELT = Path(__file__).resolve().parents[2] / "irl_sample_data" / "S20261029_134821_14-17in.csv"

# A clean trial: no artifacts, gaps, loose band or pauses unless a test asks for them.
CLEAN = replace(
    PROFILES["stable"],
    artifacts_per_hour=0,
    no_signal_per_hour=0,
    gaps_per_hour=0,
    pauses_per_hour=0,
    shallow_per_hour=0,
)


@dataclass
class SyntheticTrial:
    path: Path
    true_breaths: int  # complete breaths inside the file
    true_peaks_s: np.ndarray  # time of each true inhale peak
    duration_s: float


def make_trial(
    tmp_path: Path, seed: int = 1, duration_s: float = 150.0, **profile_changes
) -> SyntheticTrial:
    """Write a synthetic trial file in the device format and return its ground truth."""
    night = simulate_night(
        replace(CLEAN, **profile_changes), duration_s, np.random.default_rng(seed)
    )
    path = tmp_path / f"S20261110_1400{seed % 60:02d}_P01-test.csv"
    write_recording(
        night,
        path,
        device_id="NN-DEV-01",
        start_local=datetime(2026, 11, 10, 14, 0, 0),
        extra_header={"synthetic": "true"},
    )
    s = night.schedule
    complete = s.is_breath & (s.start_s >= 0) & (s.start_s + s.duration_s <= duration_s)
    peaks = s.start_s[complete] + INHALE_FRACTION * s.duration_s[complete]
    return SyntheticTrial(path, int(complete.sum()), peaks, duration_s)


# --- Scaffolding -------------------------------------------------------------------------


def test_load_trial_puts_samples_on_an_even_grid(tmp_path: Path) -> None:
    st = make_trial(tmp_path, gaps_per_hour=200, duration_s=300)
    trial = load_trial(st.path)
    assert trial.fs_hz == 25
    assert np.allclose(np.diff(trial.t_s), 0.04)
    assert trial.missed_samples > 0
    assert np.isnan(trial.L_uH).sum() == trial.missed_samples  # lost samples are NaN, not dropped
    assert 3.5 < np.nanmedian(trial.L_uH) < 4.5
    assert trial.label == "P01-test"


def test_fill_short_gaps_bridges_short_holes_only() -> None:
    x = np.arange(100.0)
    x[10:13] = np.nan  # 3 samples = 0.12 s
    x[40:90] = np.nan  # 50 samples = 2 s at 25 Hz -> bridged with max 2 s
    x[95:] = np.nan  # trailing: nothing on the right to bridge to
    y = fill_short_gaps(x, FS, max_gap_s=1.0)
    assert np.allclose(y[10:13], [10, 11, 12])
    assert np.isnan(y[40:90]).all()
    assert np.isnan(y[95:]).all()


def test_percent_error_matches_appendix_b() -> None:
    assert percent_error(31, 30) == pytest.approx(3.333, abs=1e-3)
    assert percent_error(28, 30) == pytest.approx(6.667, abs=1e-3)
    with pytest.raises(ValueError):
        percent_error(5, 0)


def test_trial_report_runs_before_processing_exists(tmp_path: Path, capsys) -> None:
    st = make_trial(tmp_path)
    counts = tmp_path / "counts.csv"
    trial_report.main([str(tmp_path), "--make-counts-template", str(counts)])
    assert counts.read_text().splitlines() == ["file,counter_1,counter_2", f"{st.path.name},,"]
    counts.write_text(
        f"file,counter_1,counter_2\n{st.path.name},{st.true_breaths},{st.true_breaths + 3}\n"
    )
    out = tmp_path / "results.csv"
    assert trial_report.main([str(tmp_path), "--counts", str(counts), "--out", str(out)]) == 0
    text = out.read_text()
    assert "counters disagree" in text
    assert st.path.name in text


def test_bench_files_without_sensor_are_reported_not_crashed(tmp_path: Path) -> None:
    bench = REAL_BELT.parent / "S20261026_205802.csv"
    if not bench.exists():
        pytest.skip("bench files are local only")
    row = trial_report.analyse(bench, (None, None))
    assert "no sensor data" in str(row["notes"])


# --- Your targets: step 2 (filters) --------------------------------------------------------


def test_remove_glitches_drops_spikes_but_keeps_real_steps() -> None:
    t = np.arange(0, 60, 1 / FS)
    x = 4.0 + 0.03 * np.sin(2 * np.pi * 0.3 * t)
    x[t >= 30] += 0.3  # the belt shifts and stays: real, must be kept
    x[500] = 1970.2  # glitch seen on the real belt
    x[900:902] = 1215.8
    y = remove_glitches(x, FS)
    assert np.isnan(y[500]) and np.isnan(y[900:902]).all()
    keep = np.ones_like(x, dtype=bool)
    keep[[500, 900, 901]] = False
    assert np.allclose(y[keep], x[keep])


def test_bandpass_keeps_breathing_without_delay_and_removes_drift() -> None:
    t = np.arange(0, 120, 1 / FS)
    breathing = 0.03 * np.sin(2 * np.pi * 0.3 * t)
    drift = 0.2 * np.sin(2 * np.pi * 0.005 * t)  # posture drift, far below 0.1 Hz
    noise = 0.01 * np.sin(2 * np.pi * 5 * t)  # well above 1 Hz
    y = bandpass(4.0 + breathing + drift + noise, FS)
    middle = slice(int(20 * FS), int(100 * FS))  # ignore the filter's edge effects
    assert abs(np.mean(y[middle])) < 0.005
    assert np.corrcoef(y[middle], breathing[middle])[0, 1] > 0.98
    # Zero phase: the peaks line up with the original's (within one sample).
    lag = np.argmax(np.correlate(y[middle], breathing[middle], "full")) - (
        len(breathing[middle]) - 1
    )
    assert abs(lag) <= 1


# --- Your targets: step 3 (breath detection) -------------------------------------------------


def test_detect_breaths_finds_each_breath_in_a_clean_trial(tmp_path: Path) -> None:
    st = make_trial(tmp_path, seed=3)
    trial = load_trial(st.path)
    result = process_trial(trial)
    detected = result.breaths.peak_times_s(trial.fs_hz)
    # Every true peak has a detected peak within 0.5 s, and there are no extras.
    matched = sum(np.min(np.abs(detected - p)) < 0.5 for p in st.true_peaks_s)
    assert matched >= len(st.true_peaks_s) - 1
    assert abs(len(detected) - len(st.true_peaks_s)) <= 1


def test_breath_hold_gives_no_peaks(tmp_path: Path) -> None:
    st = make_trial(tmp_path, seed=4, pauses_per_hour=200)  # several 5-20 s holds
    trial = load_trial(st.path)
    result = process_trial(trial)
    gaps_s = np.diff(result.breaths.peak_times_s(trial.fs_hz))
    assert gaps_s.max() > 10  # at least one hold is longer than 10 s and has no fake breaths


# --- Your targets: step 4 (metrics) ---------------------------------------------------------


@pytest.mark.parametrize("seed", [1, 2, 5, 8, 13])
def test_trial_breath_count_meets_the_5_percent_target(tmp_path: Path, seed: int) -> None:
    """Test 2 on synthetic data: whole-trial count within 5% (about 1 breath in 2.5 min)."""
    st = make_trial(tmp_path, seed=seed)
    result = process_trial(load_trial(st.path))
    assert percent_error(result.breath_count, st.true_breaths) <= 5.0


def test_per_minute_rate_is_close_to_truth_on_a_clean_night(tmp_path: Path) -> None:
    from generate_synthetic import compute_ground_truth

    duration_s = 20 * 60
    night = simulate_night(CLEAN, duration_s, np.random.default_rng(21))
    truth = np.array(compute_ground_truth(night, duration_s)["resp_rate_bpm"])
    path = tmp_path / "S20261110_140000.csv"
    write_recording(
        night, path, device_id="NN-DEV-01", start_local=datetime(2026, 11, 10, 14), extra_header={}
    )
    trial = load_trial(path)
    result = process_trial(trial)
    rr = respiratory_rate_per_minute(result.breaths, trial.fs_hz, len(trial.t_s))
    assert len(rr) == 20
    within = np.abs(rr - truth) / truth <= 0.05
    assert within.mean() >= 0.9


def test_relative_amplitude_is_about_one_for_normal_breathing(tmp_path: Path) -> None:
    st = make_trial(tmp_path, seed=6)
    result = process_trial(load_trial(st.path))
    amp = relative_amplitude(result.filtered, result.breaths)
    assert 0.9 <= np.median(amp) <= 1.1


def test_find_pauses_reports_long_holds(tmp_path: Path) -> None:
    breaths = Breaths(
        peak_idx=np.array([25, 100, 175, 600, 675]), trough_idx=np.array([0, 60, 140, 560, 640])
    )
    # Turning points at 0, 1, 2.4, 4, 5.6, 7 s, then nothing until the trough at 22.4 s.
    pauses = find_pauses(breaths, FS, min_pause_s=10)
    assert pauses == [(7.0, 22.4)]


def test_count_complete_breaths_ignores_a_half_breath_at_each_end() -> None:
    # trough, peak, trough, peak, trough, peak  -> the last peak has no trough after it.
    breaths = Breaths(peak_idx=np.array([50, 150, 250]), trough_idx=np.array([0, 100, 200]))
    assert count_complete_breaths(breaths, n_samples=270) == 2


@pytest.mark.skipif(not REAL_BELT.exists(), reason="bench files are local only")
def test_real_belt_recording_is_about_17_per_minute() -> None:
    """The firmware team's belt recording: clean breathing at ~17/min (FFT estimate)."""
    trial = load_trial(REAL_BELT)
    result = process_trial(trial)
    assert 15.5 <= result.rate_bpm <= 18.5


@pytest.mark.skipif(not REAL_BELT.exists(), reason="bench files are local only")
def test_trimming_the_settling_time_removes_fake_breaths() -> None:
    """The belt file's first ~10 s is the belt settling, not breathing (see debug plot)."""
    trial = load_trial(REAL_BELT)
    whole = process_trial(trial)
    trimmed = process_trial(trial, trim_start_s=10, trim_end_s=5)
    assert trimmed.breath_count < whole.breath_count
    assert 16 <= trimmed.rate_bpm <= 18  # the FFT estimate was 17.2 /min


def test_stuck_sensor_readings_are_removed() -> None:
    t = np.arange(0, 20, 1 / FS)
    x = 4.0 + 0.03 * np.sin(2 * np.pi * 0.3 * t)
    x[:100] = 4.05  # 4 s of the exact same plausible value: sensor not updating
    y = remove_glitches(x, FS)
    assert np.isnan(y[:100]).all()
    assert np.isfinite(y[100:]).all()


# --- Signal quality ---------------------------------------------------------------------------


def _bands_for(x: np.ndarray):
    from processing.quality import split_bands

    return split_bands(x, FS)


def test_snr_matches_the_known_signal_and_noise_power() -> None:
    from processing.quality import snr_sir_db

    rng = np.random.default_rng(0)
    t = np.arange(0, 120, 1 / FS)
    breathing = 0.03 * np.sin(2 * np.pi * 0.3 * t)  # power = 0.03^2 / 2 = 4.5e-4
    noise = rng.normal(0, 0.003, len(t))  # white: (12.5 - 1) / 12.5 of 9e-6 lies above 1 Hz
    bands = _bands_for(4.0 + breathing + noise)
    snr, _ = snr_sir_db(bands, int(20 * FS), int(100 * FS), FS)
    expected = 10 * np.log10(4.5e-4 / (9e-6 * 11.5 / 12.5))
    assert abs(snr - expected) < 1.0


def test_sir_drops_when_slow_drift_dominates() -> None:
    from processing.quality import snr_sir_db

    t = np.arange(0, 180, 1 / FS)
    breathing = 0.03 * np.sin(2 * np.pi * 0.3 * t)
    calm = _bands_for(4.0 + breathing)
    drifting = _bands_for(4.0 + breathing + 0.3 * np.sin(2 * np.pi * 0.02 * t))
    window = (int(30 * FS), int(150 * FS))
    _, sir_calm = snr_sir_db(calm, *window, FS)
    _, sir_drift = snr_sir_db(drifting, *window, FS)
    assert sir_drift < 0 < sir_calm
    _, sir_short = snr_sir_db(calm, 0, int(10 * FS), FS)
    assert np.isnan(sir_short)  # too short to measure below 0.1 Hz


def test_window_quality_labels(tmp_path: Path) -> None:
    from processing.quality import window_quality

    rng = np.random.default_rng(1)
    t = np.arange(0, 180, 1 / FS)
    x = 4.0 + 0.03 * np.sin(2 * np.pi * 0.3 * t)
    x[int(60 * FS) : int(120 * FS)] += rng.normal(0, 0.05, int(60 * FS))  # minute 2: noisy
    raw = x.copy()
    raw[int(120 * FS) :] = np.nan  # minute 3: sensor missing
    labels = [w.label for w in window_quality(raw, _bands_for(x), FS)]
    assert labels == ["good", "poor", "no_signal"]


@pytest.mark.skipif(not REAL_BELT.exists(), reason="bench files are local only")
def test_real_belt_breathing_is_good_quality() -> None:
    result = process_trial(load_trial(REAL_BELT), trim_start_s=10, trim_end_s=5)
    assert result.snr_db > 20 and result.sir_db > 15
