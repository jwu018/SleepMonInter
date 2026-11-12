"""Read a Night Night device recording (docs/DEVICE_FORMAT.md) into numpy arrays.

The Python twin of the web app's `parseDeviceCsv.ts`. Works for every firmware version so far:
columns are looked up by name, so older files simply lack the battery columns, and blank
sensor cells (no sensor connected) become NaN.

    rec = read_device_csv(Path("S20261103_143541.csv"))
    rec.column("ldc_L_uH")      # belt inductance, uH
    rec.elapsed_s               # time axis in seconds
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


@dataclass
class DeviceRecording:
    path: Path
    #: Header lines as key -> value, e.g. {"start_local": "2026-11-03 14:35:41", ...}.
    header: dict[str, str]
    firmware: str | None
    sample_rate_hz: float
    #: Numeric columns by name (everything except `datetime`). NaN where a cell was blank.
    columns: dict[str, np.ndarray]
    #: `# mark` lines: (elapsed_ms or None, note).
    marks: list[tuple[int | None, str]] = field(default_factory=list)
    #: `# stop` line as key -> value (reason, rows, missed_slots), or None if it never stopped.
    stop: dict[str, str] | None = None

    def column(self, name: str) -> np.ndarray:
        """A column by name, or an all-NaN array if this file doesn't have it."""
        if name in self.columns:
            return self.columns[name]
        return np.full(len(self.columns["elapsed_ms"]), np.nan)

    @property
    def elapsed_s(self) -> np.ndarray:
        return self.columns["elapsed_ms"] / 1000.0

    @property
    def has_sensor(self) -> bool:
        return bool(np.isfinite(self.column("ldc_L_uH")).any())


def _key_values(parts: list[str]) -> dict[str, str]:
    out = {}
    for part in parts:
        key, eq, value = part.partition("=")
        if eq:
            out[key.strip()] = value.strip()
    return out


def read_device_csv(path: Path) -> DeviceRecording:
    header: dict[str, str] = {}
    firmware: str | None = None
    marks: list[tuple[int | None, str]] = []
    stop: dict[str, str] | None = None
    names: list[str] | None = None
    data_lines: list[str] = []

    with Path(path).open(encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\r\n")
            if not line.strip():
                continue
            if line.startswith("#"):
                body = line[1:].strip()
                key, _, rest = body.partition(",")
                key = key.strip()
                if key == "mark":
                    parts = rest.split(",")
                    m = (
                        re.fullmatch(r"\s*elapsed_ms=(\d+)\s*", parts[1])
                        if len(parts) > 1
                        else None
                    )
                    note = ",".join(parts[2:] if m else parts[1:]).strip()
                    marks.append((int(m.group(1)) if m else None, note))
                elif key == "stop":
                    stop = _key_values(rest.split(",")[1:])
                elif names is None:  # header metadata only appears before the column row
                    fw = re.search(r"firmware\s+([\w.]+)", body)
                    if fw:
                        firmware = fw.group(1)
                    else:
                        header[key] = rest.strip()
                continue
            if names is None:
                names = [n.strip() for n in line.split(",")]
                continue
            data_lines.append(line)

    if names is None or "elapsed_ms" not in names:
        raise ValueError(f"{path}: not a Night Night recording (no elapsed_ms column)")

    numeric = [i for i, n in enumerate(names) if n != "datetime"]
    if data_lines:
        try:
            # Fast path: every cell filled (sensor connected).
            table = np.loadtxt(data_lines, delimiter=",", usecols=numeric, ndmin=2)
        except ValueError:
            # Blank cells (no sensor): genfromtxt turns them into NaN. Slower, but such
            # files are short bench tests.
            table = np.genfromtxt(data_lines, delimiter=",", usecols=numeric, ndmin=2)
    else:
        table = np.empty((0, len(numeric)))

    columns = {names[i]: table[:, k] for k, i in enumerate(numeric)}
    return DeviceRecording(
        path=Path(path),
        header=header,
        firmware=firmware,
        sample_rate_hz=float(header.get("sample_rate_hz", 25)),
        columns=columns,
        marks=marks,
        stop=stop,
    )
