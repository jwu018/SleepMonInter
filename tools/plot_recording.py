"""Plot a Night Night recording file for a quick visual check.

Three panels:
  1. the whole night (to spot baseline shifts, no-signal stretches and trends);
  2. a zoomed window (to see individual breaths, pauses and spikes);
  3. battery voltage.
Works on any device-format file (docs/DEVICE_FORMAT.md), real or synthetic.
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
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Patch

from device_csv import read_device_csv

GAP_THRESHOLD_MS = 1000
# Shading colors for events read from a ground-truth file (data gaps are always red).
EVENT_COLORS = {
    "pause": "tab:purple",
    "shallow": "tab:orange",
    "no_signal": "tab:gray",
    "artifact_burst": "tab:green",
}


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

    rec = read_device_csv(args.path)
    elapsed_ms = rec.columns["elapsed_ms"]
    hours = elapsed_ms / 3_600_000
    gaps = find_gaps(elapsed_ms)
    # The belt inductance is the breathing signal; without a sensor, fall back to the a0 pin.
    if rec.has_sensor:
        signal, signal_label = rec.column("ldc_L_uH"), "belt inductance (uH)"
    else:
        signal, signal_label = rec.column("a0_raw"), "a0_raw (no sensor; debug only)"

    fig, (ax_night, ax_zoom, ax_batt) = plt.subplots(
        3, 1, figsize=(13, 9), gridspec_kw={"height_ratios": [2, 2, 1]}
    )
    device = rec.header.get("device_id", "?")
    title = f"{args.path.name}  |  firmware {rec.firmware}  |  device {device}"
    if "profile" in rec.header:
        title += f"  |  profile {rec.header['profile']}, seed {rec.header.get('seed', '?')}"
    fig.suptitle(title)

    ax_night.plot(hours, signal, linewidth=0.3)
    ax_night.set_xlabel("hours since start")
    ax_night.set_ylabel(signal_label)
    ax_night.set_title("Whole night")

    zoom_start_ms = args.zoom_start_min * 60_000
    zoom_end_ms = zoom_start_ms + args.zoom_minutes * 60_000
    in_zoom = (elapsed_ms >= zoom_start_ms) & (elapsed_ms < zoom_end_ms)
    ax_zoom.plot(elapsed_ms[in_zoom] / 1000, signal[in_zoom], linewidth=0.8)
    ax_zoom.set_xlabel("seconds since start")
    ax_zoom.set_ylabel(signal_label)
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

    vbat = rec.column("vbat_v")
    logged = ~np.isnan(vbat)
    ax_batt.plot(hours[logged], vbat[logged], linewidth=1)
    ax_batt.set_xlabel("hours since start")
    ax_batt.set_ylabel("battery (V)")
    ax_batt.set_title("Battery" if logged.any() else "Battery (not logged by this firmware)")

    # Notes typed during recording ("# mark" lines).
    for elapsed, note in rec.marks:
        if elapsed is not None:
            ax_night.axvline(elapsed / 3_600_000, color="tab:purple", linewidth=1)
            ax_night.annotate(
                note,
                (elapsed / 3_600_000, 1),
                xycoords=("data", "axes fraction"),
                fontsize=7,
                rotation=90,
                va="top",
            )

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
