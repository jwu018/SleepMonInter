"""Load one recording (= one trial) onto an even time grid. Scaffolding, already working."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from device_csv import read_device_csv


@dataclass
class Trial:
    path: Path
    fs_hz: float
    #: Seconds since switch-on, evenly spaced at 1/fs_hz.
    t_s: np.ndarray
    #: Belt inductance in uH on that grid. NaN where a sample was lost or the cell was blank.
    L_uH: np.ndarray
    #: Battery voltage on the same grid (NaN for firmware without battery columns).
    vbat_v: np.ndarray
    #: `# mark` notes typed during recording: (seconds since start, text).
    marks: list[tuple[float, str]] = field(default_factory=list)
    #: Why the recording stopped ("switch", "serial", ...) or None if it ended unexpectedly.
    stop_reason: str | None = None
    #: Samples the device scheduled but didn't write (from jumps in the `sample` counter).
    missed_samples: int = 0

    @property
    def duration_s(self) -> float:
        return len(self.t_s) / self.fs_hz

    @property
    def label(self) -> str:
        """The note after the timestamp in the file name, e.g. "P03-lying-t2", or ""."""
        parts = self.path.stem.split("_", 2)
        return parts[2] if len(parts) == 3 else ""


def load_trial(path: Path) -> Trial:
    """Read a device CSV and place every sample on an even grid using its `sample` index.

    Why the sample index and not elapsed_ms? The firmware schedules sample k at k * 40 ms;
    elapsed_ms is when it was actually written, which jitters (e.g. 58 ms then 22 ms). Using
    the scheduled index gives a perfectly even grid, which filters and FFTs assume, and a
    jump in the index marks exactly which samples were lost.
    """
    rec = read_device_csv(Path(path))
    fs = rec.sample_rate_hz
    idx = rec.columns["sample"].astype(np.int64)
    if len(idx) == 0:
        raise ValueError(f"{path}: no samples")
    idx = idx - idx[0]
    n = int(idx[-1]) + 1

    def on_grid(values: np.ndarray) -> np.ndarray:
        grid = np.full(n, np.nan)
        grid[idx] = values
        return grid

    start_ms = rec.columns["elapsed_ms"][0]
    return Trial(
        path=Path(path),
        fs_hz=fs,
        t_s=np.arange(n) / fs,
        L_uH=on_grid(rec.column("ldc_L_uH")),
        vbat_v=on_grid(rec.column("vbat_v")),
        marks=[((ms - start_ms) / 1000.0, note) for ms, note in rec.marks if ms is not None],
        stop_reason=rec.stop.get("reason") if rec.stop else None,
        missed_samples=n - len(idx),
    )


def fill_short_gaps(x: np.ndarray, fs_hz: float, max_gap_s: float = 2.0) -> np.ndarray:
    """Linearly bridge NaN runs no longer than `max_gap_s`; longer runs stay NaN.

    Filters can't run across NaN, so short holes (a few lost samples, a rejected glitch) are
    bridged with a straight line. Long holes are real data gaps and must stay visible.
    """
    y = np.asarray(x, dtype=float).copy()
    missing = np.isnan(y)
    if not missing.any() or missing.all():
        return y
    max_len = int(round(max_gap_s * fs_hz))
    # Find each run of NaN as (start, end) index pairs.
    edges = np.diff(np.concatenate([[0], missing.astype(np.int8), [0]]))
    starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    good = np.flatnonzero(~missing)
    for s, e in zip(starts, ends, strict=True):
        if e - s <= max_len and s > 0 and e < len(y):  # interior and short enough
            y[s:e] = np.interp(np.arange(s, e), good, y[good])
    return y
