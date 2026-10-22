"""Tests for the web data builder's waveform packing and metric blanking."""

import numpy as np

from build_static_data import WAVEFORM_MISSING, dashboard_metrics, downsample_waveform


def test_downsample_averages_pairs_and_marks_gaps() -> None:
    # 20 samples at 50 ms, with samples 6..13 (350 ms) missing.
    timestamp_ms = np.array([i * 50 for i in range(20) if not 6 <= i <= 13], dtype=np.int64)
    raw = 50_000 + timestamp_ms // 50  # value = 50000 + sample index
    packed, offset = downsample_waveform(timestamp_ms, raw)

    assert packed.dtype == np.dtype("<i2")
    assert len(packed) == 10  # 20 samples -> 10 pairs
    restored = packed.astype(float) + offset
    # Mean of samples 0 and 1 is 50000.5; packing to whole counts rounds it by at most 0.5.
    assert abs(restored[0] - 50_000.5) <= 0.5
    assert np.all(packed[3:7] == WAVEFORM_MISSING)  # pairs (6,7) .. (12,13) are all missing


def test_no_signal_minutes_are_blanked() -> None:
    truth = {
        "minute_index": [0, 1],
        "resp_rate_bpm": [18.0, 17.5],
        "amplitude_rel": [1.0, 0.9],
        "quality": ["good", "no_signal"],
    }
    metrics = dashboard_metrics(truth)
    assert metrics["resp_rate_bpm"] == [18.0, None]
    assert metrics["amplitude_rel"] == [1.0, None]
