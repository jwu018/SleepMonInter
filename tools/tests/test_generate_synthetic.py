"""Tests for the synthetic generator: file format, timing, reproducibility, plausibility."""

import json
from dataclasses import replace
from pathlib import Path

import numpy as np

from device_csv import read_device_csv
from generate_synthetic import (
    PROFILES,
    Event,
    compute_ground_truth,
    ldc_columns,
    lipo_percent,
    main,
    minute_quality,
    simulate_night,
    truth_path_for,
)

HEADER_KEYS = {"start_local", "rtc", "sample_rate_hz", "ldc1612", "device_id"}
COLUMNS = (
    "datetime,elapsed_ms,sample,ldc_raw,ldc_freq_hz,ldc_L_uH,ldc_flags,a0_raw,vbat_v,battery_pct"
)


def generate(tmp_path: Path, *args: str) -> Path:
    """Run the CLI on a short night and return the output path."""
    out = tmp_path / "night.csv"
    main(["--duration-hours", "0.25", "--out", str(out), *args])
    return out


def test_file_matches_the_device_format(tmp_path: Path) -> None:
    path = generate(tmp_path, "--start-utc", "2026-10-01T02:30:00Z")
    rec = read_device_csv(path)
    assert rec.firmware == "0.5"
    assert HEADER_KEYS <= rec.header.keys()
    assert rec.header["sample_rate_hz"] == "25"
    assert rec.header["start_local"] == "2026-09-30 22:30:00"  # UTC-4 by default
    assert rec.stop is not None and rec.stop["rows"] == str(len(rec.elapsed_s))

    lines = path.read_text(encoding="utf-8").splitlines()
    first_data_row = next(i for i, line in enumerate(lines) if not line.startswith("#"))
    assert lines[first_data_row] == COLUMNS
    assert lines[first_data_row + 1].startswith("2026-09-30 22:30:00.000,0,0,")


def test_samples_every_40_ms_without_gaps() -> None:
    no_gaps = replace(PROFILES["stable"], gaps_per_hour=0)
    night = simulate_night(no_gaps, 600, np.random.default_rng(1))
    assert night.timestamp_ms[0] == 0
    assert np.all(np.diff(night.timestamp_ms) == 40)
    assert np.all(np.diff(night.sample_idx) == 1)


def test_gaps_show_up_as_time_and_sample_jumps() -> None:
    many_gaps = replace(PROFILES["stable"], gaps_per_hour=20)
    night = simulate_night(many_gaps, 1800, np.random.default_rng(2))
    diffs = np.diff(night.timestamp_ms)
    assert np.all(diffs > 0), "timestamps must stay strictly increasing"
    assert [e for e in night.events if e.kind == "data_gap"], "setup should produce a gap"
    assert np.count_nonzero(diffs > 1000) >= 1
    assert np.count_nonzero(np.diff(night.sample_idx) > 1) >= 1  # the sample counter jumps too


def test_same_seed_gives_identical_file(tmp_path: Path) -> None:
    a = generate(tmp_path / "a", "--seed", "7").read_bytes()
    b = generate(tmp_path / "b", "--seed", "7").read_bytes()
    c = generate(tmp_path / "c", "--seed", "8").read_bytes()
    assert a == b
    assert a != c


def test_respiratory_rate_is_plausible_for_every_profile() -> None:
    for name, profile in PROFILES.items():
        night = simulate_night(profile, 3600, np.random.default_rng(3))
        breaths = night.schedule.is_breath
        rr_bpm = 60 / night.schedule.duration_s[breaths]
        assert 12 <= np.median(rr_bpm) <= 28, name


def test_inductance_is_in_the_real_belts_range() -> None:
    night = simulate_night(PROFILES["stable"], 600, np.random.default_rng(4))
    assert 3.5 < np.median(night.L_uH) < 4.5
    # A typical breath swings L by a few hundredths of a uH, like the team's belt.
    assert 0.02 < np.percentile(night.L_uH, 95) - np.percentile(night.L_uH, 5) < 0.3


def test_sensor_columns_follow_lc_tank_physics() -> None:
    freq_hz, raw = ldc_columns(np.array([4.07657]))
    # Checked against a real row: 4.07657 uH with a 100 pF tank -> ~7.88 MHz.
    assert abs(freq_hz[0] - 7.883e6) < 0.01e6
    assert raw[0] == round(freq_hz[0] / 40e6 * 2**28)


def test_battery_updates_every_10_s_and_declines() -> None:
    night = simulate_night(PROFILES["stable"], 2 * 3600, np.random.default_rng(4))
    v = night.vbat_v
    assert len(np.unique(v[:250])) == 1  # first 10 s: one reading, held
    assert v[-1] < v[0] - 0.05
    assert np.all((v > 3.3) & (v < 4.25))
    assert np.array_equal(night.battery_pct, lipo_percent(v))
    assert lipo_percent(np.array([4.20, 3.27, 3.80]))[2] == 40  # firmware table: 3.80 V = 40%


# --- Ground truth ---------------------------------------------------------------------


def test_truth_file_is_written_next_to_the_recording(tmp_path: Path) -> None:
    out = generate(tmp_path, "--seed", "3")
    truth = json.loads(truth_path_for(out).read_text(encoding="utf-8"))
    minutes = truth["minutes"]
    assert truth["source_file"] == out.name
    assert len(minutes["minute_index"]) == 15  # 0.25 h
    assert len(minutes["resp_rate_bpm"]) == len(minutes["amplitude_rel"]) == 15
    assert set(minutes["quality"]) <= {"good", "poor", "no_signal"}


def test_truth_rr_matches_the_breath_schedule() -> None:
    no_pauses = replace(PROFILES["stable"], pauses_per_hour=0)
    night = simulate_night(no_pauses, 1800, np.random.default_rng(6))
    rr = np.array(compute_ground_truth(night, 1800)["resp_rate_bpm"])
    breaths = night.schedule.duration_s[night.schedule.is_breath]
    # Total breaths over 30 minutes must equal the sum of the per-minute rates.
    assert abs(rr.sum() - np.count_nonzero(breaths.cumsum() <= 1800)) < 1.0


def test_pause_lowers_that_minutes_rr() -> None:
    profile = replace(PROFILES["stable"], pauses_per_hour=30)
    night = simulate_night(profile, 1800, np.random.default_rng(7))
    rr = compute_ground_truth(night, 1800)["resp_rate_bpm"]
    # A long pause that sits entirely inside one minute.
    long_pause = next(
        e
        for e in night.events
        if e.kind == "pause"
        and e.end_ms - e.start_ms > 12_000
        and e.start_ms // 60_000 == (e.end_ms - 1) // 60_000
    )
    assert rr[long_pause.start_ms // 60_000] < np.median(rr)


def test_quality_labels_follow_events() -> None:
    events = [
        Event("no_signal", 60_000, 180_000),  # covers minutes 1 and 2 completely
        Event("artifact_spike", 200_000, 200_100),  # minute 3
        Event("pause", 250_000, 260_000),  # minute 4: physiology, not a quality problem
    ]
    assert minute_quality(events, 5) == ["good", "no_signal", "no_signal", "poor", "good"]
