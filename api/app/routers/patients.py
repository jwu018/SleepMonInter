"""Patient endpoints. Patients are addressed by study code (NN-001), never by a name."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from ..db import get_db
from ..models import Device, Patient, Recording
from ..schemas import PatientDetail, PatientSummary, RecordingSummary
from ..summary import minutes_by_recording, recording_summary

router = APIRouter(prefix="/patients", tags=["patients"])

Db = Annotated[Session, Depends(get_db)]
StudyCode = Annotated[str, Path(pattern=r"^NN-\d{3}$", description="Study code, e.g. NN-001")]


def _load_patient(db: Session, study_code: str) -> tuple[Patient, list[Recording]]:
    patient = db.scalar(select(Patient).where(Patient.study_code == study_code))
    if patient is None:
        raise HTTPException(404, "patient not found")
    recordings = list(
        db.scalars(
            select(Recording)
            .where(Recording.patient_id == patient.id)
            # joinedload fetches each recording's patient and device in the same query,
            # instead of one extra query per recording when we read rec.device later.
            .options(joinedload(Recording.patient), joinedload(Recording.device))
            .order_by(Recording.start_utc)
        )
    )
    return patient, recordings


def _summaries(db: Session, recordings: list[Recording]) -> list[RecordingSummary]:
    minutes = minutes_by_recording(db, (r.id for r in recordings))
    return [recording_summary(r, minutes[r.id]) for r in recordings]


@router.get("", response_model=list[PatientSummary])
def list_patients(db: Db) -> list[PatientSummary]:
    """Every patient with the number of recordings and the start of the latest one."""
    rows = db.execute(
        select(
            Patient.study_code,
            func.count(Recording.id),
            func.max(Recording.start_utc),
            # A patient uses one device in the sample data; if there were several this
            # shows the first by code.
            func.min(Recording.device_id),
        )
        .outerjoin(Recording, Recording.patient_id == Patient.id)
        .group_by(Patient.id)
        .order_by(Patient.study_code)
    ).all()
    device_codes = _device_codes(db)
    return [
        PatientSummary(
            study_code=code,
            device_id=device_codes.get(device_id, ""),
            recording_count=count,
            last_recording_start_utc=last,
        )
        for code, count, last, device_id in rows
    ]


def _device_codes(db: Session) -> dict[int, str]:
    return dict(db.execute(select(Device.id, Device.device_code)).all())


@router.get("/{study_code}", response_model=PatientDetail)
def get_patient(study_code: StudyCode, db: Db) -> PatientDetail:
    """One patient with a summary of every night."""
    patient, recordings = _load_patient(db, study_code)
    return PatientDetail(
        study_code=patient.study_code,
        device_id=recordings[0].device.device_code if recordings else "",
        recording_count=len(recordings),
        last_recording_start_utc=recordings[-1].start_utc if recordings else None,
        recordings=_summaries(db, recordings),
    )


@router.get("/{study_code}/recordings", response_model=list[RecordingSummary])
def list_patient_recordings(study_code: StudyCode, db: Db) -> list[RecordingSummary]:
    """A summary of every night for one patient, oldest first."""
    _, recordings = _load_patient(db, study_code)
    return _summaries(db, recordings)
