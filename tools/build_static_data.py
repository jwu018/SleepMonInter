"""Turn the sample set into the static files the web app reads (until the API exists).

Reads sample_data/manifest.json plus each recording's CSV and truth file, and writes:

    web/data/index.json                  patients + per-night summaries (patient list/overview)
    web/data/recordings/<id>.json        one night: metadata, summary, per-minute metrics
    web/data/waveforms/<id>.i16          belt inductance at 12.5 Hz as little-endian int16

The per-minute metrics stand in for what signal processing will produce in Phase 5. They
come from the ground truth, with RR and amplitude blanked on no_signal minutes, because
processing can't measure breathing that the band didn't record.

Why a binary waveform? A night at 12.5 Hz is 360,000 values: about 720 KB as int16 versus
about 3 MB as JSON. The web server slices and downsamples it per zoom window.

Usage (after generate_sample_set.py):
    python build_static_data.py
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from device_csv import read_device_csv

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SAMPLE_DIR = ROOT / "sample_data"
DEFAULT_OUT_DIR = ROOT / "web" / "data"

SOURCE_RATE_HZ = 25
WAVEFORM_RATE_HZ = SOURCE_RATE_HZ / 2  # 12.5 Hz: plenty to draw breaths (~0.3 Hz)
# Inductance is stored as int16 steps of 0.1 nH around the night's median: +/-3.2 uH of range
# (breaths swing ~0.06 uH, artifacts up to ~0.5 uH) at a resolution far below the noise.
WAVEFORM_SCALE_UH = 1e-4
WAVEFORM_MISSING = -32768  # int16 value meaning "no sample here" (data gap)
GAP_THRESHOLD_MS = 1000


def downsample_waveform(
    timestamp_ms: np.ndarray, values: np.ndarray, scale: float = WAVEFORM_SCALE_UH
) -> tuple[np.ndarray, float]:
    """Put samples on a regular 25 Hz grid (NaN in gaps), average pairs to 12.5 Hz, and pack
    as int16 steps of `scale` from the night's median.

    Returns (int16 array, offset). A value is restored as offset + packed * scale."""
    period_ms = 1000 // SOURCE_RATE_HZ
    n_grid = int(timestamp_ms[-1] // period_ms) + 1
    n_grid += n_grid % 2  # even length, so pairs line up
    grid = np.full(n_grid, np.nan)
    grid[(timestamp_ms // period_ms).astype(np.int64)] = values

    pairs = grid.reshape(-1, 2)
    both_missing = np.isnan(pairs).all(axis=1)
    pairs_filled = np.where(np.isnan(pairs), 0.0, pairs)
    counts = (~np.isnan(pairs)).sum(axis=1)
    averaged = np.full(len(pairs), np.nan)
    averaged[~both_missing] = pairs_filled[~both_missing].sum(axis=1) / counts[~both_missing]

    offset = float(np.nanmedian(averaged))
    packed = np.clip(np.rint((averaged - offset) / scale), -32767, 32767)
    packed[np.isnan(averaged)] = WAVEFORM_MISSING
    return packed.astype("<i2"), offset


def dashboard_metrics(truth_minutes: dict[str, list]) -> dict[str, list]:
    """Ground truth -> what the dashboard shows: blank RR/amplitude where there's no signal."""
    quality = truth_minutes["quality"]
    return {
        "minute_index": truth_minutes["minute_index"],
        "resp_rate_bpm": [
            None if q == "no_signal" else v
            for v, q in zip(truth_minutes["resp_rate_bpm"], quality, strict=True)
        ],
        "amplitude_rel": [
            None if q == "no_signal" else v
            for v, q in zip(truth_minutes["amplitude_rel"], quality, strict=True)
        ],
        "quality": quality,
    }


def summarize(metrics: dict[str, list]) -> dict[str, float | None]:
    rr = [v for v in metrics["resp_rate_bpm"] if v is not None]
    amp = [v for v in metrics["amplitude_rel"] if v is not None]
    quality = metrics["quality"]
    n = len(quality) or 1
    return {
        "median_resp_rate_bpm": round(float(np.median(rr)), 1) if rr else None,
        "mean_amplitude_rel": round(float(np.mean(amp)), 2) if amp else None,
        "pct_good": round(100 * quality.count("good") / n, 1),
        "pct_poor": round(100 * quality.count("poor") / n, 1),
        "pct_no_signal": round(100 * quality.count("no_signal") / n, 1),
    }


def format_utc(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def build(sample_dir: Path, out_dir: Path) -> None:
    manifest = json.loads((sample_dir / "manifest.json").read_text(encoding="utf-8"))

    # Start clean so deleted recordings don't linger.
    for sub in ("recordings", "waveforms"):
        shutil.rmtree(out_dir / sub, ignore_errors=True)
        (out_dir / sub).mkdir(parents=True)

    summaries_by_patient: dict[str, list[dict]] = {
        p["study_code"]: [] for p in manifest["patients"]
    }
    for entry in manifest["recordings"]:
        rec = read_device_csv(sample_dir / entry["csv"])
        elapsed_ms = rec.columns["elapsed_ms"]
        truth = json.loads((sample_dir / entry["truth"]).read_text(encoding="utf-8"))
        recording_id = entry["recording_id"]

        # The device file only knows local clock time; the generator recorded UTC in the truth file.
        start = datetime.fromisoformat(truth["start_utc"])
        period_ms = 1000 / rec.sample_rate_hz
        end = start + timedelta(milliseconds=float(elapsed_ms[-1]) + period_ms)
        vbat = rec.column("vbat_v")
        battery_mv = np.rint(vbat[np.isfinite(vbat)] * 1000)
        gap_count = int(np.count_nonzero(np.diff(elapsed_ms) > GAP_THRESHOLD_MS))

        metrics = dashboard_metrics(truth["minutes"])
        summary = {
            "recording_id": recording_id,
            "study_code": entry["study_code"],
            "device_id": rec.header.get("device_id", entry["device_id"]),
            "start_utc": format_utc(start),
            "end_utc": format_utc(end),
            "duration_min": round((end - start).total_seconds() / 60, 1),
            "battery_start_mv": int(battery_mv[0]),
            "battery_end_mv": int(battery_mv[-1]),
            "gap_count": gap_count,
            **summarize(metrics),
        }
        summaries_by_patient[entry["study_code"]].append(summary)

        waveform, offset = downsample_waveform(elapsed_ms, rec.column("ldc_L_uH"))
        (out_dir / "waveforms" / f"{recording_id}.i16").write_bytes(waveform.tobytes())

        detail = {
            **summary,
            "sample_period_ms": round(period_ms),
            "status": "processed",
            "metrics": metrics,
            "waveform": {
                "sample_rate_hz": WAVEFORM_RATE_HZ,
                "offset": offset,
                "scale": WAVEFORM_SCALE_UH,
                "unit": "µH",
                "n_samples": len(waveform),
                "missing_value": WAVEFORM_MISSING,
            },
        }
        (out_dir / "recordings" / f"{recording_id}.json").write_text(
            json.dumps(detail, separators=(",", ":")), encoding="utf-8"
        )
        print(f"  {recording_id}: {len(waveform):,} waveform points, {gap_count} gap(s)")

    patients = []
    for patient in manifest["patients"]:
        nights = sorted(summaries_by_patient[patient["study_code"]], key=lambda s: s["start_utc"])
        patients.append(
            {
                "study_code": patient["study_code"],
                "device_id": patient["device_id"],
                "recording_count": len(nights),
                "last_recording_start_utc": nights[-1]["start_utc"] if nights else None,
                "recordings": nights,
            }
        )
    index = {"synthetic": True, "patients": patients}
    (out_dir / "index.json").write_text(json.dumps(index, indent=1) + "\n", encoding="utf-8")
    print(f"Wrote {out_dir}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build web/data from the sample set.")
    parser.add_argument("--sample-dir", type=Path, default=DEFAULT_SAMPLE_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)
    build(args.sample_dir, args.out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
