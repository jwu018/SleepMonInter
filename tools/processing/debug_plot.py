"""Debug plots for processing. Scaffolding, already working.

    python -m processing.debug_plot ../irl_sample_data/S20261029_134821_14-17in.csv
    python -m processing.debug_plot trial.csv --save trial.png

Panels: raw inductance (lost samples shown as gaps), then the filtered signal with detected
peaks/troughs once your functions exist. Until then it just plots the raw signal and says
which step is missing. Pass `true_peaks_s` (from synthetic ground truth) to see detection
errors as markers on the same axis.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from .load import Trial, load_trial
from .pipeline import TrialResult, process_trial


def plot_trial(
    trial: Trial,
    result: TrialResult | None = None,
    true_peaks_s: np.ndarray | None = None,
    note: str = "",
):
    fig, (ax_raw, ax_filt) = plt.subplots(2, 1, figsize=(13, 7), sharex=True)
    title = (
        f"{trial.path.name}  |  {trial.duration_s:.1f} s  |  stop: {trial.stop_reason or 'MISSING'}"
    )
    if result is not None:
        title += f"  |  {result.breath_count} breaths = {result.rate_bpm:.1f} /min"
    fig.suptitle(title)

    ax_raw.plot(trial.t_s, trial.L_uH, linewidth=0.8, label="raw")
    if result is not None:
        ax_raw.plot(trial.t_s, result.cleaned, linewidth=0.8, alpha=0.7, label="cleaned")
        ax_raw.legend(loc="upper right", fontsize=8)
    ax_raw.set_ylabel("inductance (uH)")
    for t, text in trial.marks:
        ax_raw.axvline(t, color="tab:purple", linewidth=1)
        ax_raw.annotate(
            text, (t, 1), xycoords=("data", "axes fraction"), fontsize=7, rotation=90, va="top"
        )

    if result is None:
        ax_filt.text(
            0.5,
            0.5,
            note or "processing not available yet",
            ha="center",
            va="center",
            transform=ax_filt.transAxes,
        )
    else:
        f = result.filtered
        ax_filt.plot(trial.t_s, f, linewidth=0.8, color="tab:blue")
        b = result.breaths
        ax_filt.plot(b.peak_idx / trial.fs_hz, f[b.peak_idx], "v", color="tab:red", label="peaks")
        ax_filt.plot(
            b.trough_idx / trial.fs_hz, f[b.trough_idx], "^", color="tab:green", label="troughs"
        )
        if true_peaks_s is not None:
            for t in true_peaks_s:
                ax_filt.axvline(t, color="gray", linewidth=0.5, alpha=0.6)
        ax_filt.legend(loc="upper right", fontsize=8)
    ax_filt.set_ylabel("filtered (uH)")
    ax_filt.set_xlabel("seconds since switch-on")
    fig.tight_layout()
    return fig


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plot a trial with the processing steps.")
    parser.add_argument("path", type=Path)
    parser.add_argument("--save", type=Path, help="write a PNG instead of opening a window")
    args = parser.parse_args(argv)

    trial = load_trial(args.path)
    result, note = None, ""
    try:
        result = process_trial(trial)
    except NotImplementedError as err:
        note = str(err)
    except ValueError as err:
        note = str(err)
    fig = plot_trial(trial, result, note=note)
    if args.save:
        fig.savefig(args.save, dpi=120)
        print(f"Saved {args.save}")
    else:
        plt.show()
    if note:
        print(note)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
