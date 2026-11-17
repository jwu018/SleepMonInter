"""Recording endpoints: metadata, per-minute metrics, and the raw signal for a time window."""

from __future__ import annotations

from typing import Annotated

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ..db import get_db
from ..downsample import downsample
from ..models import MinuteMetric, Recording
from ..schemas import MinuteMetrics, RecordingMeta, WaveformWindow
from ..storage import FileStore, get_store, load_waveform, waveform_meta_path
from ..summary import minutes_by_recording, recording_meta

router = APIRouter(prefix="/recordings", tags=["recordings"])

Db = Annotated[Session, Depends(get_db)]
RecordingCode = Annotated[
    str, Path(pattern=r"^NN-\d{3}_\d{4}-\d{2}-\d{2}$", description="e.g. NN-001_2026-09-14")
]


def _load_recording(db: Session, code: str) -> Recording:
    rec = db.scalar(
        select(Recording)
        .where(Recording.code == code)
        .options(joinedload(Recording.patient), joinedload(Recording.device))
    )
    if rec is None:
        raise HTTPException(404, "recording not found")
    return rec


@router.get("/{recording_id}", response_model=RecordingMeta)
def get_recording(recording_id: RecordingCode, db: Db) -> RecordingMeta:
    """Metadata and the night summary: median rate, quality shares, battery."""
    rec = _load_recording(db, recording_id)
    return recording_meta(rec, minutes_by_recording(db, [rec.id])[rec.id])


@router.get("/{recording_id}/metrics", response_model=MinuteMetrics)
def get_metrics(recording_id: RecordingCode, db: Db) -> MinuteMetrics:
    """Per-minute respiratory rate, relative amplitude and quality for the whole night."""
    rec = _load_recording(db, recording_id)
    rows = db.execute(
        select(
            MinuteMetric.minute_index,
            MinuteMetric.resp_rate_bpm,
            MinuteMetric.amplitude_rel,
            MinuteMetric.quality,
        )
        .where(MinuteMetric.recording_id == rec.id)
        .order_by(MinuteMetric.minute_index)
    ).all()
    return MinuteMetrics(
        minute_index=[r[0] for r in rows],
        resp_rate_bpm=[r[1] for r in rows],
        amplitude_rel=[r[2] for r in rows],
        quality=[r[3] for r in rows],
    )


@router.get("/{recording_id}/waveform", response_model=WaveformWindow)
def get_waveform(
    recording_id: RecordingCode,
    db: Db,
    store: Annotated[FileStore, Depends(get_store)],
    start_ms: Annotated[float, Query(ge=0, description="ms since recording start")] = 0,
    end_ms: Annotated[float | None, Query(ge=0, description="default: end of recording")] = None,
    max_points: Annotated[int, Query(ge=10, le=10_000)] = 2000,
) -> WaveformWindow:
    """The raw signal for [start_ms, end_ms), reduced to about `max_points` points with LTTB."""
    rec = _load_recording(db, recording_id)
    path = rec.waveform_path
    if not path or not store.exists(path) or not store.exists(waveform_meta_path(path)):
        raise HTTPException(404, "no stored signal for this recording")
    wave = load_waveform(store, path)

    ms_per_sample = 1000.0 / wave.sample_rate_hz
    n = len(wave.values)
    first = min(n, int(start_ms // ms_per_sample))
    last = n if end_ms is None else min(n, int(np.ceil(end_ms / ms_per_sample)))
    if last < first:
        raise HTTPException(422, "end_ms must not be before start_ms")

    t_ms = np.arange(first, last) * ms_per_sample
    times, values, reduced = downsample(t_ms, wave.values[first:last], max_points)
    return WaveformWindow(
        start_ms=first * ms_per_sample,
        end_ms=last * ms_per_sample,
        t_ms=times,
        raw_value=values,
        unit=wave.unit,
        resolution="lttb" if reduced else "raw",
    )
