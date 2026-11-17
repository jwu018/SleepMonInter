"""Check an uploaded device file before it is accepted (format: docs/DEVICE_FORMAT.md).

Two kinds of finding:
- errors:   the file cannot be used. The upload is rejected and nothing is stored.
- warnings: the file is usable but something is worth knowing (data gaps, power cut, ...).
            The upload is accepted and the warnings are shown to the person uploading.

A data gap is never an error: a night with a few lost seconds is still a night.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from pydantic import BaseModel

from ..toolbox import read_device_csv

MAX_FILE_BYTES = 100 * 1024 * 1024  # a 10-hour night is about 60-70 MB
GAP_THRESHOLD_MS = 1000
MAX_GAPS_LISTED = 50
REQUIRED_HEADER_KEYS = ("start_local", "sample_rate_hz")
SUPPORTED_RATE_HZ = 25.0
START_FORMAT = "%Y-%m-%d %H:%M:%S"


class Gap(BaseModel):
    start_ms: int
    length_ms: int


class ValidationReport(BaseModel):
    ok: bool
    errors: list[str] = []
    warnings: list[str] = []
    firmware: str | None = None
    device_id: str | None = None
    #: Device clock time at switch-on, as written in the file (no time zone).
    start_local: str | None = None
    sample_rate_hz: float | None = None
    rows: int = 0
    duration_s: float = 0.0
    missed_samples: int = 0
    gap_count: int = 0
    gaps: list[Gap] = []
    has_sensor: bool = False
    #: True when the file ends with a `# stop` line (the recording was ended on purpose).
    clean_stop: bool = False
    battery_start_mv: int | None = None
    battery_end_mv: int | None = None


def parse_start_local(text: str) -> datetime:
    return datetime.strptime(text.strip(), START_FORMAT)


def start_utc_from(report: ValidationReport, utc_offset_hours: float) -> datetime:
    """Device clock time -> UTC. The device has no time zone, so the uploader supplies it."""
    from datetime import UTC

    local = parse_start_local(report.start_local or "")
    return (local - timedelta(hours=utc_offset_hours)).replace(tzinfo=UTC)


def validate_recording(path: Path) -> ValidationReport:
    size = path.stat().st_size
    if size > MAX_FILE_BYTES:
        return ValidationReport(
            ok=False,
            errors=[f"file is {size / 1e6:.0f} MB; the limit is {MAX_FILE_BYTES / 1e6:.0f} MB"],
        )
    try:
        rec = read_device_csv(path)
    except (ValueError, UnicodeDecodeError) as err:
        # Covers "no elapsed_ms column", non-numeric cells and files that are not text.
        return ValidationReport(ok=False, errors=[f"not a Night Night recording: {err}"])

    errors: list[str] = []
    warnings: list[str] = []
    report = ValidationReport(
        ok=False,
        firmware=rec.firmware,
        device_id=rec.header.get("device_id") or None,
        start_local=rec.header.get("start_local") or None,
        sample_rate_hz=rec.sample_rate_hz,
        has_sensor=rec.has_sensor,
        clean_stop=rec.stop is not None,
    )

    for key in REQUIRED_HEADER_KEYS:
        if not rec.header.get(key):
            errors.append(f"missing header line: # {key},...")
    if report.start_local:
        try:
            parse_start_local(report.start_local)
        except ValueError:
            errors.append(f"start_local is not a date and time: {report.start_local!r}")

    elapsed_ms = rec.columns["elapsed_ms"]
    report.rows = len(elapsed_ms)
    if report.rows == 0:
        errors.append("the file has a header but no samples")
    elif not np.isfinite(elapsed_ms).all():
        errors.append("some rows have no elapsed_ms value")
    else:
        steps = np.diff(elapsed_ms)
        if (steps < 0).any():
            row = int(np.flatnonzero(steps < 0)[0]) + 2
            errors.append(f"time goes backwards at data row {row} (elapsed_ms must never decrease)")
        else:
            period_ms = 1000.0 / rec.sample_rate_hz
            report.duration_s = round(float(elapsed_ms[-1] - elapsed_ms[0] + period_ms) / 1000, 1)
            gap_at = np.flatnonzero(steps > GAP_THRESHOLD_MS)
            report.gap_count = len(gap_at)
            report.gaps = [
                Gap(start_ms=int(elapsed_ms[i]), length_ms=int(steps[i]))
                for i in gap_at[:MAX_GAPS_LISTED]
            ]
            if report.gap_count:
                longest = float(steps[gap_at].max()) / 1000
                warnings.append(
                    f"{report.gap_count} data gap(s) longer than 1 s (longest {longest:.0f} s)"
                )
            if "sample" in rec.columns and report.rows > 1:
                index = rec.columns["sample"]
                report.missed_samples = int(index[-1] - index[0] + 1 - report.rows)

    if rec.sample_rate_hz != SUPPORTED_RATE_HZ:
        errors.append(f"sample rate {rec.sample_rate_hz:g} Hz is not supported (expected 25 Hz)")
    if not rec.has_sensor:
        warnings.append(
            "no sensor data: the inductance column is blank, so nothing can be analysed"
        )
    if not report.clean_stop:
        warnings.append("no '# stop' line: the recording ended unexpectedly (power cut?)")
    if not report.device_id:
        warnings.append("no device_id in the header")

    vbat = rec.column("vbat_v")
    vbat = vbat[np.isfinite(vbat)]
    if len(vbat):
        report.battery_start_mv = int(round(float(vbat[0]) * 1000))
        report.battery_end_mv = int(round(float(vbat[-1]) * 1000))
    else:
        warnings.append("no battery voltage in this file (older firmware)")

    report.errors, report.warnings, report.ok = errors, warnings, not errors
    return report
