"""Run the breathing algorithm on a stored recording and save the results.

Called in the background right after an upload, and again by POST /recordings/{id}/process.
The recording's `status` tells the dashboard where it is:

    uploaded -> processing -> processed      (per-minute metrics and the signal file exist)
                           -> failed         (error_message says why)
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable

import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .models import MinuteMetric, Recording
from .storage import FileStore
from .toolbox import (
    WAVEFORM_MISSING,
    WAVEFORM_RATE_HZ,
    WAVEFORM_SCALE_UH,
    amplitude_per_minute,
    downsample_waveform,
    load_trial,
    process_trial,
    respiratory_rate_per_minute,
)

log = logging.getLogger(__name__)


def _number(value: float, digits: int) -> float | None:
    return None if not np.isfinite(value) else round(float(value), digits)


def _analyse(rec: Recording, store: FileStore, db: Session) -> None:
    if not rec.raw_file_path:
        raise ValueError("no raw file is stored for this recording")
    trial = load_trial(store.local_path(rec.raw_file_path))
    result = process_trial(trial)  # raises ValueError when the file has no sensor data
    fs = trial.fs_hz
    n_minutes = int(len(trial.t_s) // (60 * fs))

    rate = respiratory_rate_per_minute(result.breaths, fs, len(trial.t_s))
    amplitude = amplitude_per_minute(result.filtered, result.breaths, fs, n_minutes)
    labels = [w.label for w in result.quality]

    db.execute(delete(MinuteMetric).where(MinuteMetric.recording_id == rec.id))
    rows = []
    for i in range(min(n_minutes, len(labels))):
        # A minute with no usable signal gets no rate or amplitude: better blank than wrong.
        usable = labels[i] != "no_signal"
        rows.append(
            {
                "recording_id": rec.id,
                "minute_index": i,
                "resp_rate_bpm": _number(rate[i], 2) if usable else None,
                "amplitude_rel": _number(amplitude[i], 3) if usable else None,
                "quality": labels[i],
            }
        )
    if rows:
        db.execute(MinuteMetric.__table__.insert(), rows)

    # The compact signal file the waveform endpoint reads (12.5 Hz int16, gaps marked).
    present = np.flatnonzero(np.isfinite(trial.L_uH))
    packed, offset = downsample_waveform(
        np.rint(present * 1000 / fs).astype(np.int64), trial.L_uH[present]
    )
    path = f"waveforms/{rec.code}.i16"
    store.save(path, packed.tobytes())
    meta = {
        "sample_rate_hz": WAVEFORM_RATE_HZ,
        "offset": offset,
        "scale": WAVEFORM_SCALE_UH,
        "unit": "µH",
        "n_samples": len(packed),
        "missing_value": WAVEFORM_MISSING,
    }
    store.save(f"waveforms/{rec.code}.json", json.dumps(meta).encode("utf-8"))
    rec.waveform_path = path


def process_recording(
    recording_id: int, session_factory: Callable[[], Session], store: FileStore
) -> None:
    """Analyse one recording. Never raises: a failure is recorded on the recording itself.

    It opens its own database session, because it runs after the upload request (and that
    request's session) has finished.
    """
    with session_factory() as db:
        rec = db.scalar(select(Recording).where(Recording.id == recording_id))
        if rec is None:
            return
        rec.status, rec.error_message = "processing", None
        db.commit()  # visible to the dashboard straight away
        try:
            _analyse(rec, store, db)
            rec.status = "processed"
            db.commit()
        except Exception as err:  # noqa: BLE001  (any failure must end up as status=failed)
            db.rollback()
            log.exception("processing %s failed", rec.code)
            rec.status, rec.error_message = "failed", str(err)[:500]
            db.commit()
