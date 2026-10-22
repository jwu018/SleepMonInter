"""Plot a Night Night recording file for a quick visual check.

Three panels:
  1. the whole night (to spot baseline shifts, no-signal stretches and trends);
  2. a zoomed window (to see individual breaths, pauses and spikes);
  3. battery voltage.
Data gaps (timestamp jumps > 1 s) are shaded red in the top two panels. If a
`<name>.truth.json` file sits next to the recording, injected events are shaded too.

Usage:
    python plot_recording.py night.csv
    python plot_recording.py night.csv --zoom-start-min 95 --zoom-minutes 2
    python plot_recording.py night.csv --save night.png
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Patch

GAP_THRESHOLD_MS = 1000
# Shading colors for events read from a ground-truth file (data gaps are always red).
EVENT_COLORS = {
    "pause": "tab:purple",
    "shallow": "tab:orange",
    "no_signal": "tab:gray",
    "artifact_burst": "tab:green",
}


@dataclass
class Recording:
    header: dict[str, str]
    timestamp_ms: np.ndarray
    raw_value: np.ndarray
    battery_mv: np.ndarray  # NaN where not logged


def read_recording(path: Path) -> Recording:
    """Minimal reader for plotting. (The validating parser comes later, in api/app/ingest/.)"""
    header: dict[str, str] = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.startswith("#"):
                break
            key, _, value = line[1:].strip().partition("=")
            header[key] = value

    # Skip the header lines explicitly: with names=True, genfromtxt would otherwise read the
    # first "# key=value" comment as the column names. Empty battery cells become NaN.
    data = np.genfromtxt(path, delimiter=",", skip_header=len(header), names=True)
    return Recording(
        header=header,
        timestamp_ms=data["timestamp_ms"].astype(np.int64),
        raw_value=data["raw_value"],
        battery_mv=data["battery_mv"],
    )


def find_gaps(timestamp_ms: np.ndarray) -> list[tuple[int, int]]:
    """(start_ms, end_ms) for every jump between consecutive samples longer than 1 s."""
    jumps = np.flatnonzero(np.diff(timestamp_ms) > GAP_THRESHOLD_MS)
    return [(int(timestamp_ms[i]), int(timestamp_ms[i + 1])) for i in jumps]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plot a Night Night recording.")
    parser.add_argument("path", type=Path)
    parser.add_argument("--zoom-start-min", type=float, default=60.0)
    parser.add_argument("--zoom-minutes", type=float, default=2.0)
    parser.add_argument("--save", type=Path, help="write a PNG instead of opening a window")
    args = parser.parse_args(argv)

    rec = read_recording(args.path)
    hours = rec.timestamp_ms / 3_600_000
    gaps = find_gaps(rec.timestamp_ms)

    fig, (ax_night, ax_zoom, ax_batt) = plt.subplots(
        3, 1, figsize=(13, 9), gridspec_kw={"height_ratios": [2, 2, 1]}
    )
    title = f"{args.path.name}  |  device {rec.header.get('device_id', '?')}"
    if "profile" in rec.header:
        title += f"  |  profile {rec.header['profile']}, seed {rec.header.get('seed', '?')}"
    fig.suptitle(title)

    ax_night.plot(hours, rec.raw_value, linewidth=0.3)
    ax_night.set_xlabel("hours since start")
    ax_night.set_ylabel("raw_value (counts)")
    ax_night.set_title("Whole night")

    zoom_start_ms = args.zoom_start_min * 60_000
    zoom_end_ms = zoom_start_ms + args.zoom_minutes * 60_000
    in_zoom = (rec.timestamp_ms >= zoom_start_ms) & (rec.timestamp_ms < zoom_end_ms)
    ax_zoom.plot(rec.timestamp_ms[in_zoom] / 1000, rec.raw_value[in_zoom], linewidth=0.8)
    ax_zoom.set_xlabel("seconds since start")
    ax_zoom.set_ylabel("raw_value (counts)")
    ax_zoom.set_title(f"Zoom: {args.zoom_minutes:g} min from minute {args.zoom_start_min:g}")

    # If the generator's ground-truth file is next to the recording, mark the injected events.
    truth_path = args.path.with_name(args.path.stem + ".truth.json")
    if truth_path.exists():
        events = json.loads(truth_path.read_text(encoding="utf-8"))["events"]
        for event in events:
            color = EVENT_COLORS.get(event["kind"])
            if color is None:
                continue
            start_ms, end_ms = event["start_ms"], max(event["end_ms"], event["start_ms"] + 2000)
            ax_night.axvspan(start_ms / 3_600_000, end_ms / 3_600_000, color=color, alpha=0.25)
            if end_ms > zoom_start_ms and start_ms < zoom_end_ms:
                ax_zoom.axvspan(start_ms / 1000, end_ms / 1000, color=color, alpha=0.2)
        handles = [Patch(color=c, alpha=0.4, label=k) for k, c in EVENT_COLORS.items()]
        ax_night.legend(handles=handles, loc="upper left", fontsize=7, ncol=len(handles))

    for start_ms, end_ms in gaps:
        ax_night.axvspan(start_ms / 3_600_000, end_ms / 3_600_000, color="red", alpha=0.3)
        # Only shade gaps that overlap the zoom window, or the x-axis stretches to include them.
        if end_ms > zoom_start_ms and start_ms < zoom_end_ms:
            ax_zoom.axvspan(start_ms / 1000, end_ms / 1000, color="red", alpha=0.3)
    ax_zoom.set_xlim(zoom_start_ms / 1000, zoom_end_ms / 1000)

    logged = ~np.isnan(rec.battery_mv)
    ax_batt.plot(hours[logged], rec.battery_mv[logged], marker=".", linestyle="none")
    ax_batt.set_xlabel("hours since start")
    ax_batt.set_ylabel("battery (mV)")
    ax_batt.set_title("Battery (logged once per minute)")

    fig.tight_layout()
    if args.save:
        fig.savefig(args.save, dpi=120)
        print(f"Saved {args.save}. Data gaps found: {len(gaps)}")
    else:
        print(f"Data gaps found: {len(gaps)}")
        plt.show()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
