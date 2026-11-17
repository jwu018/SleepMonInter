"""The database tables, as SQLAlchemy 2.0 classes. One class = one table.

All tables live in the `public` schema of Postgres. The `auth` and `storage` schemas belong
to Supabase and are never touched from here. Patients are identified only by study codes:
no names, no birthdates, nothing identifying.

Times are stored as UTC (`timestamptz`). Signal times inside a recording are milliseconds
since the recording started.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

RECORDING_STATUSES = ("uploaded", "processing", "processed", "failed")
QUALITIES = ("good", "poor", "no_signal")


def _one_of(column: str, values: tuple[str, ...]) -> str:
    """SQL for a CHECK constraint: the column must hold one of these words."""
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(primary_key=True)
    study_code: Mapped[str] = mapped_column(String(16), unique=True)  # e.g. NN-001
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    recordings: Mapped[list[Recording]] = relationship(back_populates="patient")


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_code: Mapped[str] = mapped_column(String(32), unique=True)  # e.g. NN-DEV-01
    notes: Mapped[str | None] = mapped_column(Text)


class Recording(Base):
    __tablename__ = "recordings"
    __table_args__ = (
        CheckConstraint(_one_of("status", RECORDING_STATUSES), name="recordings_status_valid"),
        Index("ix_recordings_patient_start", "patient_id", "start_utc"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    #: Public identifier used in URLs, e.g. NN-001_2026-09-14.
    code: Mapped[str] = mapped_column(String(64), unique=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"))
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"))
    start_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sample_period_ms: Mapped[int]
    #: Paths inside the file store (see storage.py), not absolute paths on one computer.
    raw_file_path: Mapped[str | None] = mapped_column(String(255))
    waveform_path: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="uploaded")
    error_message: Mapped[str | None] = mapped_column(Text)
    battery_start_mv: Mapped[int | None]
    battery_end_mv: Mapped[int | None]
    gap_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    patient: Mapped[Patient] = relationship(back_populates="recordings")
    device: Mapped[Device] = relationship()
    minutes: Mapped[list[MinuteMetric]] = relationship(
        back_populates="recording", order_by="MinuteMetric.minute_index"
    )


class MinuteMetric(Base):
    """One row per minute of a recording: the numbers the trend charts draw."""

    __tablename__ = "minute_metrics"
    __table_args__ = (
        CheckConstraint(_one_of("quality", QUALITIES), name="minute_metrics_quality_valid"),
    )

    # Two columns together are the primary key: one row per (recording, minute).
    recording_id: Mapped[int] = mapped_column(
        ForeignKey("recordings.id", ondelete="CASCADE"), primary_key=True
    )
    minute_index: Mapped[int] = mapped_column(primary_key=True)
    resp_rate_bpm: Mapped[float | None]
    amplitude_rel: Mapped[float | None]
    quality: Mapped[str] = mapped_column(String(16))

    recording: Mapped[Recording] = relationship(back_populates="minutes")


class Annotation(Base):
    """A clinician note on a moment (end_ms is NULL) or a stretch of a recording.

    The table exists so the schema is complete. The dashboard still keeps annotations in the
    browser until endpoints for them are added.
    """

    __tablename__ = "annotations"
    __table_args__ = (Index("ix_annotations_recording", "recording_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    recording_id: Mapped[int] = mapped_column(ForeignKey("recordings.id", ondelete="CASCADE"))
    start_ms: Mapped[int]
    end_ms: Mapped[int | None]
    category: Mapped[str] = mapped_column(String(32))
    note: Mapped[str] = mapped_column(Text, default="")
    #: The Supabase Auth user id (a UUID as text). No foreign key: `auth` belongs to Supabase.
    author_user_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


#: Every table this app owns. Migrations enable Row Level Security on each of them.
APP_TABLES = ("patients", "devices", "recordings", "minute_metrics", "annotations")
