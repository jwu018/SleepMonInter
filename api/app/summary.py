"""Turn database rows into the response shapes, including the night summary numbers."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import MinuteMetric, Recording
from .schemas import RecordingMeta, RecordingSummary

#: (resp_rate_bpm, amplitude_rel, quality) for one minute.
MinuteRow = tuple[float | None, float | None, str]


def night_stats(minutes: Sequence[MinuteRow]) -> dict[str, float | None]:
    """Median rate, mean amplitude and the share of each quality label for one night.

    Same rounding as tools/build_static_data.py, so API and static data show equal numbers.
    """
    rates = [r for r, _, _ in minutes if r is not None]
    amplitudes = [a for _, a, _ in minutes if a is not None]
    labels = [q for _, _, q in minutes]
    n = len(labels) or 1

    def pct(label: str) -> float:
        return round(100 * labels.count(label) / n, 1)

    return {
        "median_resp_rate_bpm": round(median(rates), 1) if rates else None,
        "mean_amplitude_rel": round(sum(amplitudes) / len(amplitudes), 2) if amplitudes else None,
        "pct_good": pct("good"),
        "pct_poor": pct("poor"),
        "pct_no_signal": pct("no_signal"),
    }


def minutes_by_recording(db: Session, recording_ids: Iterable[int]) -> dict[int, list[MinuteRow]]:
    """All minute rows for several recordings in ONE query (not one query per recording)."""
    ids = list(recording_ids)
    out: dict[int, list[MinuteRow]] = defaultdict(list)
    if not ids:
        return out
    rows = db.execute(
        select(
            MinuteMetric.recording_id,
            MinuteMetric.resp_rate_bpm,
            MinuteMetric.amplitude_rel,
            MinuteMetric.quality,
        ).where(MinuteMetric.recording_id.in_(ids))
    )
    for recording_id, rate, amplitude, quality in rows:
        out[recording_id].append((rate, amplitude, quality))
    return out


def _fields(rec: Recording, minutes: Sequence[MinuteRow]) -> dict[str, object]:
    return {
        "recording_id": rec.code,
        "study_code": rec.patient.study_code,
        "device_id": rec.device.device_code,
        "start_utc": rec.start_utc,
        "end_utc": rec.end_utc,
        "duration_min": round((rec.end_utc - rec.start_utc).total_seconds() / 60, 1),
        "battery_start_mv": rec.battery_start_mv,
        "battery_end_mv": rec.battery_end_mv,
        "gap_count": rec.gap_count,
        **night_stats(minutes),
    }


def recording_summary(rec: Recording, minutes: Sequence[MinuteRow]) -> RecordingSummary:
    return RecordingSummary(**_fields(rec, minutes))


def recording_meta(rec: Recording, minutes: Sequence[MinuteRow]) -> RecordingMeta:
    return RecordingMeta(
        **_fields(rec, minutes),
        sample_period_ms=rec.sample_period_ms,
        status=rec.status,
        error_message=rec.error_message,
    )
