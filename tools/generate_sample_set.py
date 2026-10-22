"""Generate the standard synthetic sample set: 3 patients x 4 nights.

Every night uses a fixed seed, so running this again reproduces byte-identical files.
That's why only the small files are committed: the ~9 MB raw CSVs are gitignored and
anyone can recreate them with one command.

Output (in sample_data/ by default):
    manifest.json                       which file belongs to which patient and device
    NN-001/NN-001_2026-09-14.csv        raw recording (gitignored)
    NN-001/NN-001_2026-09-14.truth.json ground truth (committed)
    ...

Usage:
    python generate_sample_set.py
    python generate_sample_set.py --out-dir ../sample_data
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from generate_synthetic import PROFILES, Profile, format_utc, generate_recording, truth_path_for

DEFAULT_OUT_DIR = Path(__file__).resolve().parent.parent / "sample_data"
NIGHTS_PER_PATIENT = 4
FIRST_NIGHT = datetime(2026, 9, 14, tzinfo=UTC)


@dataclass(frozen=True)
class SamplePatient:
    study_code: str
    device_id: str
    profile_name: str
    days_between_nights: int


PATIENTS = [
    SamplePatient("NN-001", "NN-DEV-01", "stable", days_between_nights=7),
    SamplePatient("NN-002", "NN-DEV-02", "declining", days_between_nights=5),
    SamplePatient("NN-003", "NN-DEV-03", "noisy", days_between_nights=6),
]


def profile_for_night(patient: SamplePatient, night_index: int) -> Profile:
    """The patient's profile, adjusted so the 'declining' patient gets worse night by night.

    This gives the patient overview's per-night trend something to show.
    """
    profile = PROFILES[patient.profile_name]
    if patient.profile_name != "declining":
        return profile
    # A narrow starting range plus a per-night shift, so the night-to-night rise isn't
    # hidden by random variation in where each night starts.
    low = profile.rr_start_bpm[0] + 1.2 * night_index
    return replace(
        profile,
        rr_start_bpm=(low, low + 1.0),
        amplitude_end=profile.amplitude_end - 0.04 * night_index,
        pauses_per_hour=profile.pauses_per_hour + 0.5 * night_index,
    )


def night_schedule(patient_number: int, night_index: int) -> tuple[timedelta, float]:
    """(lights-off offset from midnight UTC, duration in hours) for one night.

    Bedtimes vary between 21:45 and 23:00 US Eastern (01:45-03:00 UTC), and recordings
    last 7-9 hours. Derived from the indices, so it's deterministic without randomness.
    """
    bedtime_minutes = 105 + ((patient_number * 37 + night_index * 23) % 76)
    duration_hours = 7.0 + ((patient_number * 3 + night_index * 5) % 9) * 0.25
    return timedelta(minutes=bedtime_minutes), duration_hours


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the 3 x 4 synthetic sample set.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)
    out_dir: Path = args.out_dir

    recordings = []
    for patient_number, patient in enumerate(PATIENTS, start=1):
        first_night = FIRST_NIGHT + timedelta(days=patient_number - 1)
        for night_index in range(NIGHTS_PER_PATIENT):
            bedtime, duration_hours = night_schedule(patient_number, night_index)
            start_utc = (
                first_night + timedelta(days=night_index * patient.days_between_nights) + bedtime
            )
            name = f"{patient.study_code}_{start_utc:%Y-%m-%d}"
            csv_path = out_dir / patient.study_code / f"{name}.csv"
            seed = patient_number * 100 + night_index

            generate_recording(
                profile_name=patient.profile_name,
                profile=profile_for_night(patient, night_index),
                seed=seed,
                duration_hours=duration_hours,
                start_utc=start_utc,
                device_id=patient.device_id,
                out=csv_path,
            )
            recordings.append(
                {
                    "recording_id": name,
                    "study_code": patient.study_code,
                    "device_id": patient.device_id,
                    "profile": patient.profile_name,
                    "seed": seed,
                    "start_utc": format_utc(start_utc),
                    "duration_hours": duration_hours,
                    "csv": csv_path.relative_to(out_dir).as_posix(),
                    "truth": truth_path_for(csv_path).relative_to(out_dir).as_posix(),
                }
            )
            print(f"  {name}  ({patient.profile_name}, {duration_hours:g} h, seed {seed})")

    manifest = {
        "description": "Synthetic Night Night sample set. Regenerate with "
        "`python tools/generate_sample_set.py`.",
        "patients": [
            {"study_code": p.study_code, "device_id": p.device_id, "profile": p.profile_name}
            for p in PATIENTS
        ],
        "recordings": recordings,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(recordings)} recordings and manifest.json to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
