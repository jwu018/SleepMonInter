"""Pydantic schemas: the shapes of the JSON the API sends.

Field names match `web/src/lib/data/types.ts` exactly, so the dashboard can read API
responses and its bundled static files with the same code.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, PlainSerializer


def _iso_utc(value: datetime) -> str:
    """2026-09-14T02:22:00Z. A time without a zone (SQLite in tests) is taken as UTC."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


UtcDatetime = Annotated[datetime, PlainSerializer(_iso_utc, return_type=str)]
Quality = Literal["good", "poor", "no_signal"]
RecordingStatus = Literal["uploaded", "processing", "processed", "failed"]


class Health(BaseModel):
    status: Literal["ok"]
    service: str
    version: str


class RecordingSummary(BaseModel):
    """One night, as listed on the patient overview."""

    recording_id: str
    study_code: str
    device_id: str
    start_utc: UtcDatetime
    end_utc: UtcDatetime
    duration_min: float
    battery_start_mv: int | None
    battery_end_mv: int | None
    gap_count: int
    median_resp_rate_bpm: float | None
    mean_amplitude_rel: float | None
    pct_good: float
    pct_poor: float
    pct_no_signal: float


class RecordingMeta(RecordingSummary):
    """A night with its metadata and summary (the metrics come from /metrics)."""

    sample_period_ms: int
    status: RecordingStatus
    #: Why processing failed, when status is "failed".
    error_message: str | None = None


class PatientSummary(BaseModel):
    study_code: str
    device_id: str
    recording_count: int
    last_recording_start_utc: UtcDatetime | None


class PatientDetail(PatientSummary):
    recordings: list[RecordingSummary]


class MinuteMetrics(BaseModel):
    """Per-minute metrics, column by column (one list per field, all the same length)."""

    minute_index: list[int]
    resp_rate_bpm: list[float | None]
    amplitude_rel: list[float | None]
    quality: list[Quality]


class WaveformWindow(BaseModel):
    """A downsampled slice of the raw signal, ready to plot."""

    start_ms: float
    end_ms: float
    t_ms: list[float]
    raw_value: list[float | None]  # None = data gap
    unit: str
    #: "raw" = every stored point in the window; "lttb" = reduced with LTTB (downsample.py).
    resolution: Literal["raw", "lttb"]
