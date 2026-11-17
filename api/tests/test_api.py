"""The read endpoints, against the small test database in conftest.py."""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.downsample import downsample, lttb_indices
from app.main import app
from app.storage import LocalFileStore
from app.summary import night_stats

from .conftest import GAP, N_SAMPLES, RECORDING, SAMPLE_RATE_HZ

MS_PER_SAMPLE = 1000 / SAMPLE_RATE_HZ


# --- Patients -----------------------------------------------------------------------------


def test_list_patients_counts_recordings(client: TestClient) -> None:
    patients = client.get("/patients").json()
    assert [p["study_code"] for p in patients] == ["NN-001", "NN-002"]
    assert patients[0]["recording_count"] == 2
    assert patients[0]["last_recording_start_utc"] == "2026-09-21T02:22:00Z"
    assert patients[0]["device_id"] == "NN-DEV-01"
    assert patients[1] == {
        "study_code": "NN-002",
        "device_id": "",
        "recording_count": 0,
        "last_recording_start_utc": None,
    }


def test_patient_detail_lists_nights_oldest_first_with_summaries(client: TestClient) -> None:
    patient = client.get("/patients/NN-001").json()
    nights = patient["recordings"]
    assert [n["recording_id"] for n in nights] == [RECORDING, "NN-001_2026-09-21"]
    first = nights[0]
    assert first["duration_min"] == 4.0
    assert first["median_resp_rate_bpm"] == 20.0  # median of 18, 20, 22
    assert first["mean_amplitude_rel"] == 1.0
    assert (first["pct_good"], first["pct_poor"], first["pct_no_signal"]) == (50.0, 25.0, 25.0)
    # A night with no minute rows yet (e.g. just uploaded) has empty stats, not an error.
    assert nights[1]["median_resp_rate_bpm"] is None
    assert client.get("/patients/NN-001/recordings").json() == nights


@pytest.mark.parametrize("path", ["/patients/NN-999", "/patients/NN-999/recordings"])
def test_unknown_patient_is_404(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 404


def test_malformed_study_code_is_rejected(client: TestClient) -> None:
    assert client.get("/patients/robert'); drop table patients;--").status_code == 422


# --- Recordings ---------------------------------------------------------------------------


def test_recording_metadata(client: TestClient) -> None:
    rec = client.get(f"/recordings/{RECORDING}").json()
    assert rec["study_code"] == "NN-001"
    assert rec["start_utc"] == "2026-09-14T02:22:00Z"
    assert rec["end_utc"] == "2026-09-14T02:26:00Z"
    assert rec["sample_period_ms"] == 40
    assert rec["status"] == "processed"
    assert (rec["battery_start_mv"], rec["battery_end_mv"], rec["gap_count"]) == (4130, 3736, 1)
    assert "metrics" not in rec


def test_metrics_are_columns_in_minute_order(client: TestClient) -> None:
    m = client.get(f"/recordings/{RECORDING}/metrics").json()
    assert m["minute_index"] == [0, 1, 2, 3]
    assert m["resp_rate_bpm"] == [18.0, 20.0, None, 22.0]
    assert m["amplitude_rel"] == [1.0, 1.2, None, 0.8]
    assert m["quality"] == ["good", "good", "no_signal", "poor"]


def test_unknown_recording_is_404(client: TestClient) -> None:
    for suffix in ("", "/metrics", "/waveform"):
        assert client.get(f"/recordings/NN-001_2030-01-01{suffix}").status_code == 404


def test_night_stats_handles_an_empty_night() -> None:
    stats = night_stats([])
    assert stats["median_resp_rate_bpm"] is None
    assert stats["pct_good"] == 0.0


# --- Waveform -----------------------------------------------------------------------------


def test_short_window_returns_every_sample(client: TestClient) -> None:
    w = client.get(f"/recordings/{RECORDING}/waveform?start_ms=0&end_ms=8000").json()
    assert w["resolution"] == "raw"
    assert w["unit"] == "µH"
    assert len(w["t_ms"]) == 100  # 8 s at 12.5 Hz
    assert w["t_ms"][1] - w["t_ms"][0] == MS_PER_SAMPLE
    assert w["raw_value"][0] == pytest.approx(4.1)  # offset + 0 * scale
    assert max(w["raw_value"]) == pytest.approx(4.13, abs=1e-3)  # offset + 300 * scale


def test_whole_recording_is_reduced_and_keeps_the_gap(client: TestClient) -> None:
    w = client.get(f"/recordings/{RECORDING}/waveform?max_points=500").json()
    assert w["resolution"] == "lttb"
    assert w["end_ms"] == N_SAMPLES * MS_PER_SAMPLE
    assert 400 <= len(w["t_ms"]) <= 520
    assert w["t_ms"] == sorted(w["t_ms"])
    # Exactly one None, at the first lost sample: the chart breaks its line there.
    gaps = [t for t, v in zip(w["t_ms"], w["raw_value"], strict=True) if v is None]
    assert gaps == [GAP.start * MS_PER_SAMPLE]
    # No kept point lies inside the gap, and the breathing envelope survives.
    inside = [t for t in w["t_ms"] if GAP.start * MS_PER_SAMPLE < t < GAP.stop * MS_PER_SAMPLE]
    assert inside == []
    values = [v for v in w["raw_value"] if v is not None]
    assert max(values) == pytest.approx(4.13, abs=1e-3)
    assert min(values) == pytest.approx(4.07, abs=1e-3)


def test_window_past_the_end_is_empty_not_an_error(client: TestClient) -> None:
    w = client.get(f"/recordings/{RECORDING}/waveform?start_ms=99999999").json()
    assert w["t_ms"] == []


def test_waveform_rejects_bad_parameters(client: TestClient) -> None:
    base = f"/recordings/{RECORDING}/waveform"
    assert client.get(f"{base}?max_points=5").status_code == 422
    assert client.get(f"{base}?start_ms=-1").status_code == 422
    assert client.get(f"{base}?start_ms=5000&end_ms=1000").status_code == 422


def test_recording_without_a_stored_signal_is_404(client: TestClient) -> None:
    assert client.get("/recordings/NN-001_2026-09-21/waveform").status_code == 404


def test_lttb_keeps_the_ends_and_a_spike() -> None:
    x = np.arange(1000.0)
    y = np.sin(x / 50)
    y[503] = 25.0  # one-sample spike that "every Nth point" would almost surely drop
    keep = lttb_indices(x, y, 50)
    assert len(keep) == 50
    assert keep[0] == 0 and keep[-1] == 999
    assert np.all(np.diff(keep) > 0)
    assert 503 in keep


def test_downsample_leaves_short_signals_alone() -> None:
    t, v, reduced = downsample(np.arange(5.0), np.array([1.0, 2.0, np.nan, 4.0, 5.0]), 100)
    assert not reduced
    assert v == [1.0, 2.0, None, 4.0, 5.0]
    assert t == [0.0, 1.0, 2.0, 3.0, 4.0]


# --- Storage and security -----------------------------------------------------------------


def test_file_store_refuses_paths_outside_its_folder(store: LocalFileStore) -> None:
    with pytest.raises(ValueError, match="escapes"):
        store.read_bytes("../outside.txt")


def test_data_routes_need_the_shared_secret_when_one_is_set(client: TestClient) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(api_shared_secret="s3cret")
    assert client.get("/patients").status_code == 401
    assert client.get("/patients", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/patients", headers={"X-API-Key": "s3cret"}).status_code == 200
    assert client.get("/health").status_code == 200  # liveness stays open
