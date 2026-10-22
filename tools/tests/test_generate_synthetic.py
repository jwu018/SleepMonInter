"""Tests for the synthetic generator: file format, timing, reproducibility, plausibility."""

from dataclasses import replace
from pathlib import Path

import numpy as np

from generate_synthetic import PROFILES, main, simulate_night
from plot_recording import read_recording

REQUIRED_HEADER_KEYS = {
    "night_night_format",
    "device_id",
    "firmware",
    "start_utc",
    "sample_period_ms",
}


def generate(tmp_path: Path, *args: str) -> Path:
    """Run the CLI on a short night and return the output path."""
    out = tmp_path / "night.csv"
    main(["--duration-hours", "0.25", "--out", str(out), *args])
    return out


def test_header_and_columns_match_format(tmp_path: Path) -> None:
    rec = read_recording(generate(tmp_path))
    assert REQUIRED_HEADER_KEYS <= rec.header.keys()
    assert rec.header["sample_period_ms"] == "50"
    assert rec.header["start_utc"].endswith("Z")

    lines = generate(tmp_path).read_text(encoding="utf-8").splitlines()
    first_data_row = next(i for i, line in enumerate(lines) if not line.startswith("#"))
    assert lines[first_data_row] == "timestamp_ms,raw_value,battery_mv"


def test_timestamps_step_by_50_ms_without_gaps() -> None:
    no_gaps = replace(PROFILES["stable"], gaps_per_hour=0)
    night = simulate_night(no_gaps, 600, np.random.default_rng(1))
    assert night.timestamp_ms[0] == 0
    assert np.all(np.diff(night.timestamp_ms) == 50)


def test_gaps_show_up_as_timestamp_jumps_over_1_s() -> None:
    many_gaps = replace(PROFILES["stable"], gaps_per_hour=20)
    night = simulate_night(many_gaps, 1800, np.random.default_rng(2))
    diffs = np.diff(night.timestamp_ms)
    assert np.all(diffs > 0), "timestamps must stay strictly increasing"
    gap_events = [e for e in night.events if e.kind == "data_gap"]
    assert gap_events, "test setup should produce at least one gap"
    assert np.count_nonzero(diffs > 1000) >= 1


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


def test_battery_logged_once_per_minute_and_declines() -> None:
    night = simulate_night(PROFILES["stable"], 2 * 3600, np.random.default_rng(4))
    logged = ~np.isnan(night.battery_mv)
    assert np.all(night.timestamp_ms[logged] % 60_000 == 0)
    battery = night.battery_mv[logged]
    assert battery[-1] < battery[0] - 50
    assert np.all((battery > 3300) & (battery < 4250))


def test_raw_values_are_unsigned_integers() -> None:
    night = simulate_night(PROFILES["noisy"], 1800, np.random.default_rng(5))
    assert night.raw_value.dtype.kind == "i"
    assert night.raw_value.min() >= 0
