"""Load the synthetic sample set into the database and the file store.

    python seed.py              # insert or refresh every sample recording
    python seed.py --no-raw     # skip copying the big raw CSV files
    python seed.py --files-only # only restore the signal files; leave the database alone

Source: `web/data/` (built by tools/build_static_data.py and committed), so the API serves
exactly the numbers the static dashboard shows. For each recording this writes:
- rows in patients, devices, recordings and minute_metrics (the ground-truth metrics);
- the compact signal file (`waveforms/<id>.i16` + `.json`) into the file store;
- the raw device CSV from `sample_data/` into the file store, when it exists on this
  computer (those files are large and not in git).

Running it again is safe: a recording that already exists is replaced, not duplicated.
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_engine
from app.models import Device, MinuteMetric, Patient, Recording
from app.storage import LocalFileStore

REPO = Path(__file__).resolve().parents[1]
WEB_DATA = REPO / "web" / "data"
SAMPLE_DATA = REPO / "sample_data"


def get_or_create(db: Session, model: type, **unique: str):
    row = db.scalar(select(model).filter_by(**unique))
    if row is None:
        row = model(**unique)
        db.add(row)
        db.flush()  # sends the INSERT now, so row.id is filled in
    return row


def restore_signal_files(store: LocalFileStore, code: str) -> str:
    """Copy one recording's compact signal file and its description into the file store."""
    detail = json.loads((WEB_DATA / "recordings" / f"{code}.json").read_text(encoding="utf-8"))
    waveform_path = f"waveforms/{code}.i16"
    store.save(waveform_path, (WEB_DATA / "waveforms" / f"{code}.i16").read_bytes())
    store.save(f"waveforms/{code}.json", json.dumps(detail["waveform"]).encode("utf-8"))
    return waveform_path


def seed_recording(db: Session, store: LocalFileStore, summary: dict, copy_raw: bool) -> None:
    code = summary["recording_id"]
    detail = json.loads((WEB_DATA / "recordings" / f"{code}.json").read_text(encoding="utf-8"))
    patient = get_or_create(db, Patient, study_code=summary["study_code"])
    device = get_or_create(db, Device, device_code=summary["device_id"])

    waveform_path = restore_signal_files(store, code)

    raw_path = None
    raw_source = SAMPLE_DATA / summary["study_code"] / f"{code}.csv"
    if copy_raw and raw_source.exists():
        raw_path = f"raw/{code}.csv"
        target = store.root / raw_path
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists() or target.stat().st_size != raw_source.stat().st_size:
            shutil.copyfile(raw_source, target)  # streamed copy: these files are ~55 MB

    # Replace an existing recording: its minute rows go with it (ON DELETE CASCADE).
    db.execute(delete(Recording).where(Recording.code == code))
    rec = Recording(
        code=code,
        patient_id=patient.id,
        device_id=device.id,
        start_utc=datetime.fromisoformat(detail["start_utc"]),
        end_utc=datetime.fromisoformat(detail["end_utc"]),
        sample_period_ms=detail["sample_period_ms"],
        raw_file_path=raw_path,
        waveform_path=waveform_path,
        status=detail["status"],
        battery_start_mv=detail["battery_start_mv"],
        battery_end_mv=detail["battery_end_mv"],
        gap_count=detail["gap_count"],
    )
    db.add(rec)
    db.flush()
    m = detail["metrics"]
    # One INSERT with many rows instead of ~500 single inserts over the network.
    db.execute(
        MinuteMetric.__table__.insert(),
        [
            {
                "recording_id": rec.id,
                "minute_index": i,
                "resp_rate_bpm": rate,
                "amplitude_rel": amp,
                "quality": quality,
            }
            for i, rate, amp, quality in zip(
                m["minute_index"], m["resp_rate_bpm"], m["amplitude_rel"], m["quality"], strict=True
            )
        ],
    )
    print(f"  {code}: {len(m['minute_index'])} minutes, raw file {'copied' if raw_path else '-'}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load the synthetic sample set.")
    parser.add_argument("--no-raw", action="store_true", help="do not copy the raw CSV files")
    parser.add_argument(
        "--files-only",
        action="store_true",
        help="only put the sample signal files back in the file store (used when a host "
        "restarts with an empty disk); the database is not touched",
    )
    args = parser.parse_args(argv)

    index = json.loads((WEB_DATA / "index.json").read_text(encoding="utf-8"))
    if not index.get("synthetic"):
        raise SystemExit("web/data is not marked synthetic: refusing to load it")
    store = LocalFileStore(get_settings().file_store_path)
    if args.files_only:
        for patient in index["patients"]:
            for summary in patient["recordings"]:
                restore_signal_files(store, summary["recording_id"])
        print(f"Signal files restored in {store.root}")
        return 0
    with Session(get_engine()) as db:
        for patient in index["patients"]:
            print(patient["study_code"])
            for summary in patient["recordings"]:
                seed_recording(db, store, summary, copy_raw=not args.no_raw)
        db.commit()  # everything above is one transaction: all of it is saved, or none
    print(f"Done. Files are in {store.root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
