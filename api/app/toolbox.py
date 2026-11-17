"""One door to the shared Python code in `tools/` (file reader + breathing algorithm).

The algorithm already exists twice: Python in `tools/processing/` (the reference) and
TypeScript for in-browser uploads. A third copy inside api/ would drift, so the API imports
the reference directly. `tools/` is a folder of scripts, not an installed package, so this
module adds it to the import path. Everything else in api/ imports from here, never from
`tools/` itself, which keeps that trick in one place.

Deployment note: the API image must contain `tools/` as well as `api/` (see the Dockerfile).
"""

from __future__ import annotations

import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[2] / "tools"
if not TOOLS_DIR.is_dir():
    raise RuntimeError(f"expected the shared tools folder at {TOOLS_DIR}")
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from build_static_data import (  # noqa: E402
    WAVEFORM_MISSING,
    WAVEFORM_RATE_HZ,
    WAVEFORM_SCALE_UH,
    downsample_waveform,
)
from device_csv import DeviceRecording, read_device_csv  # noqa: E402
from processing.load import Trial, load_trial  # noqa: E402
from processing.metrics import (  # noqa: E402
    amplitude_per_minute,
    respiratory_rate_per_minute,
)
from processing.pipeline import TrialResult, process_trial  # noqa: E402

__all__ = [
    "WAVEFORM_MISSING",
    "WAVEFORM_RATE_HZ",
    "WAVEFORM_SCALE_UH",
    "DeviceRecording",
    "Trial",
    "TrialResult",
    "amplitude_per_minute",
    "downsample_waveform",
    "load_trial",
    "process_trial",
    "read_device_csv",
    "respiratory_rate_per_minute",
]
