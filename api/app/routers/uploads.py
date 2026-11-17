"""Upload a device file, and (re)run processing on a stored recording."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Path,
    UploadFile,
)
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..db import get_db, get_session_factory
from ..ingest.validate import MAX_FILE_BYTES, ValidationReport, start_utc_from, validate_recording
from ..models import Device, Patient, Recording
from ..process import process_recording
from ..schemas import RecordingStatus
from ..storage import FileStore, get_store

router = APIRouter(prefix="/recordings", tags=["upload"])

Db = Annotated[Session, Depends(get_db)]
Store = Annotated[FileStore, Depends(get_store)]
SessionFactory = Annotated[Callable[[], Session], Depends(get_session_factory)]


class UploadResult(BaseModel):
    recording_id: str
    status: RecordingStatus
    report: ValidationReport


class ProcessStarted(BaseModel):
    recording_id: str
    status: RecordingStatus


@router.post("/upload", response_model=UploadResult, status_code=201)
def upload_recording(
    background: BackgroundTasks,
    db: Db,
    store: Store,
    session_factory: SessionFactory,
    file: Annotated[UploadFile, File(description="The S*.csv file from the microSD card")],
    study_code: Annotated[str, Form(pattern=r"^NN-\d{3}$")],
    utc_offset_hours: Annotated[
        float, Form(ge=-12, le=14, description="Device clock minus UTC, e.g. -5 for US Eastern")
    ] = -5.0,
    replace: Annotated[bool, Form(description="Overwrite a recording with the same id")] = False,
) -> UploadResult:
    """Store a device file for a patient, validate it, and start processing.

    Answers straight away with the validation report. Processing continues in the
    background: poll GET /recordings/{recording_id} until `status` is processed or failed.
    """
    patient = db.scalar(select(Patient).where(Patient.study_code == study_code))
    if patient is None:
        raise HTTPException(404, "patient not found")

    # 1. Save under a temporary name. The real name depends on the start time inside the file.
    incoming = f"incoming/{study_code}_{id(file)}.csv"
    try:
        store.save_stream(incoming, file.file, MAX_FILE_BYTES)
    except OverflowError as err:
        raise HTTPException(413, f"file is larger than {MAX_FILE_BYTES // 2**20} MB") from err

    # 2. Validate. A file with errors is deleted, and the report says what is wrong.
    report = validate_recording(store.local_path(incoming))
    if not report.ok:
        store.delete(incoming)
        raise HTTPException(422, detail=report.model_dump())

    start_utc = start_utc_from(report, utc_offset_hours)
    code = f"{study_code}_{start_utc:%Y-%m-%d}"
    existing = db.scalar(select(Recording).where(Recording.code == code))
    if existing is not None:
        if not replace:
            store.delete(incoming)
            raise HTTPException(409, f"{code} already exists (send replace=true to overwrite it)")
        db.execute(delete(Recording).where(Recording.id == existing.id))

    raw_path = f"raw/{code}.csv"
    store.move(incoming, raw_path)

    device_code = report.device_id or "unknown"
    device = db.scalar(select(Device).where(Device.device_code == device_code))
    if device is None:
        device = Device(device_code=device_code)
        db.add(device)
        db.flush()

    rec = Recording(
        code=code,
        patient_id=patient.id,
        device_id=device.id,
        start_utc=start_utc,
        end_utc=start_utc + timedelta(seconds=report.duration_s),
        sample_period_ms=round(1000 / (report.sample_rate_hz or 25)),
        raw_file_path=raw_path,
        status="uploaded",
        battery_start_mv=report.battery_start_mv,
        battery_end_mv=report.battery_end_mv,
        gap_count=report.gap_count,
    )
    db.add(rec)
    db.commit()

    # 3. Process after the response has been sent, so a big file does not hold up the upload.
    background.add_task(process_recording, rec.id, session_factory, store)
    return UploadResult(recording_id=code, status="uploaded", report=report)


@router.post("/{recording_id}/process", response_model=ProcessStarted, status_code=202)
def reprocess_recording(
    recording_id: Annotated[str, Path(pattern=r"^NN-\d{3}_\d{4}-\d{2}-\d{2}$")],
    background: BackgroundTasks,
    db: Db,
    store: Store,
    session_factory: SessionFactory,
) -> ProcessStarted:
    """Run the algorithm again on the stored raw file (for example after improving it)."""
    rec = db.scalar(select(Recording).where(Recording.code == recording_id))
    if rec is None:
        raise HTTPException(404, "recording not found")
    if not rec.raw_file_path or not store.exists(rec.raw_file_path):
        raise HTTPException(409, "no raw file is stored for this recording")
    rec.status, rec.error_message = "uploaded", None
    db.commit()
    background.add_task(process_recording, rec.id, session_factory, store)
    return ProcessStarted(recording_id=rec.code, status="uploaded")
