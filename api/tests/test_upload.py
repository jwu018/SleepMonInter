"""Upload, validation and processing, using small device files built in memory."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.ingest.validate import validate_recording

HEADER = """# Night Night respiratory logger, firmware 0.5
# start_local,2026-11-10 21:30:00
# rtc,DS3231 ok
# sample_rate_hz,25
# ldc1612,channel 1, tank 100 pF, drive 20
# device_id,NN-DEV-07
# synthetic,true
datetime,elapsed_ms,sample,ldc_raw,ldc_freq_hz,ldc_L_uH,ldc_flags,a0_raw,vbat_v,battery_pct
"""


def device_file(
    duration_s: float = 200.0,
    rate_bpm: float = 15.0,
    drop: slice | None = None,
    stop: bool = True,
    header: str = HEADER,
) -> bytes:
    """A device CSV with steady breathing at `rate_bpm`. `drop` removes rows (a data gap)."""
    k = np.arange(int(duration_s * 25))
    if drop is not None:
        k = np.delete(k, drop)
    t = k / 25
    L = 4.1 - 0.03 * np.cos(2 * np.pi * rate_bpm / 60 * t)
    vbat = 4.1 - 0.0001 * t
    rows = [
        f"2026-11-10 21:30:00.000,{i * 40},{i},0,0,{v:.5f},0,650,{b:.3f},90"
        for i, v, b in zip(k, L, vbat, strict=True)
    ]
    tail = f"# stop,2026-11-10 21:33:20.000,reason=switch,rows={len(k)},missed_slots=0\n"
    return (header + "\n".join(rows) + "\n" + (tail if stop else "")).encode("utf-8")


def upload(client: TestClient, content: bytes, **form: str):
    return client.post(
        "/recordings/upload",
        files={"file": ("S20261110_213000.csv", content, "text/csv")},
        data={"study_code": "NN-002", **form},
    )


# --- Validator ----------------------------------------------------------------------------


def test_valid_file_passes_with_facts(tmp_path: Path) -> None:
    path = tmp_path / "ok.csv"
    path.write_bytes(device_file())
    report = validate_recording(path)
    assert report.ok and report.errors == []
    assert report.warnings == []
    assert (report.rows, report.duration_s, report.gap_count) == (5000, 200.0, 0)
    assert report.device_id == "NN-DEV-07"
    assert report.firmware == "0.5"
    assert report.clean_stop and report.has_sensor
    assert report.battery_start_mv == 4100 and report.battery_end_mv == 4080


def test_gaps_and_missing_stop_are_warnings_not_errors(tmp_path: Path) -> None:
    path = tmp_path / "gap.csv"
    path.write_bytes(device_file(drop=slice(1000, 1250), stop=False))  # 10 s lost at 40 s
    report = validate_recording(path)
    assert report.ok
    assert report.gap_count == 1
    assert report.gaps[0].start_ms == 39_960 and report.gaps[0].length_ms == 10_040
    assert report.missed_samples == 250
    assert any("data gap" in w for w in report.warnings)
    assert any("ended unexpectedly" in w for w in report.warnings)


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (
            device_file(header=HEADER.replace("# start_local,2026-11-10 21:30:00\n", "")),
            "start_local",
        ),
        (device_file(header=HEADER.replace("# sample_rate_hz,25\n", "")), "sample_rate_hz"),
        (device_file(header=HEADER.replace("21:30:00", "half past nine")), "not a date"),
        (HEADER.encode("utf-8"), "no samples"),
        (b"name,value\nfoo,1\n", "not a Night Night recording"),
        (b"\xff\xfe\x00\x01 not text at all", "not a Night Night recording"),
    ],
    ids=["no-start", "no-rate", "bad-start", "no-rows", "other-csv", "binary"],
)
def test_unusable_files_are_rejected(tmp_path: Path, content: bytes, expected: str) -> None:
    path = tmp_path / "bad.csv"
    path.write_bytes(content)
    report = validate_recording(path)
    assert not report.ok
    assert any(expected in e for e in report.errors), report.errors


def test_time_going_backwards_is_an_error(tmp_path: Path) -> None:
    lines = device_file(duration_s=10).decode().splitlines()
    lines[20], lines[21] = lines[21], lines[20]  # swap two data rows
    path = tmp_path / "backwards.csv"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    report = validate_recording(path)
    assert any("backwards" in e for e in report.errors)


# --- Upload + processing ------------------------------------------------------------------


def test_upload_stores_processes_and_serves_the_recording(client: TestClient, store) -> None:
    response = upload(client, device_file(duration_s=200, rate_bpm=15))
    assert response.status_code == 201, response.text
    body = response.json()
    # 21:30 device time at UTC-5 is 02:30 UTC the next day.
    assert body["recording_id"] == "NN-002_2026-11-11"
    assert body["status"] == "uploaded"
    assert body["report"]["ok"] is True
    assert store.exists("raw/NN-002_2026-11-11.csv")
    assert not any((store.root / "incoming").iterdir())

    # TestClient runs the background job before returning, so processing is already done.
    rec = client.get("/recordings/NN-002_2026-11-11").json()
    assert rec["status"] == "processed"
    assert rec["start_utc"] == "2026-11-11T02:30:00Z"
    assert rec["end_utc"] == "2026-11-11T02:33:20Z"
    assert rec["device_id"] == "NN-DEV-07"
    assert rec["median_resp_rate_bpm"] == pytest.approx(15.0, abs=0.3)

    metrics = client.get("/recordings/NN-002_2026-11-11/metrics").json()
    assert metrics["minute_index"] == [0, 1, 2]
    assert metrics["amplitude_rel"][1] == pytest.approx(1.0, abs=0.05)

    wave = client.get("/recordings/NN-002_2026-11-11/waveform?max_points=400").json()
    assert wave["resolution"] == "lttb"
    assert max(wave["raw_value"]) == pytest.approx(4.13, abs=2e-3)

    nights = client.get("/patients/NN-002").json()["recordings"]
    assert [n["recording_id"] for n in nights] == ["NN-002_2026-11-11"]


def test_upload_with_the_time_zone_given(client: TestClient) -> None:
    body = upload(client, device_file(), utc_offset_hours="0").json()
    assert body["recording_id"] == "NN-002_2026-11-10"


def test_duplicate_upload_needs_replace(client: TestClient) -> None:
    assert upload(client, device_file()).status_code == 201
    assert upload(client, device_file()).status_code == 409
    again = upload(client, device_file(rate_bpm=20), replace="true")
    assert again.status_code == 201
    rec = client.get("/recordings/NN-002_2026-11-11").json()
    assert rec["median_resp_rate_bpm"] == pytest.approx(20.0, abs=0.3)


def test_invalid_file_is_rejected_and_not_kept(client: TestClient, store) -> None:
    response = upload(client, b"name,value\nfoo,1\n")
    assert response.status_code == 422
    assert response.json()["detail"]["ok"] is False
    assert not any((store.root / "incoming").iterdir())
    assert client.get("/patients/NN-002").json()["recording_count"] == 0


def test_upload_for_unknown_patient_is_404(client: TestClient) -> None:
    response = client.post(
        "/recordings/upload",
        files={"file": ("x.csv", device_file(duration_s=5), "text/csv")},
        data={"study_code": "NN-999"},
    )
    assert response.status_code == 404


def test_file_without_sensor_data_ends_as_failed(client: TestClient) -> None:
    blank = device_file(duration_s=30).decode().splitlines()
    out = []
    for line in blank:
        cells = line.split(",")
        if not line.startswith("#") and cells[0] != "datetime":
            cells[3] = cells[4] = cells[5] = ""  # sensor columns blank
        out.append(",".join(cells))
    response = upload(client, ("\n".join(out) + "\n").encode("utf-8"))
    assert response.status_code == 201  # accepted, with a warning
    assert any("no sensor data" in w for w in response.json()["report"]["warnings"])
    rec = client.get("/recordings/NN-002_2026-11-11").json()
    assert rec["status"] == "failed"
    assert "no sensor data" in rec["error_message"]


def test_reprocess_runs_again(client: TestClient) -> None:
    upload(client, device_file())
    response = client.post("/recordings/NN-002_2026-11-11/process")
    assert response.status_code == 202
    assert client.get("/recordings/NN-002_2026-11-11").json()["status"] == "processed"
    # A seeded recording with no raw file cannot be reprocessed.
    assert client.post("/recordings/NN-001_2026-09-21/process").status_code == 409
