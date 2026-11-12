"""Breathing-accuracy report for Technical Memo 3, Test 2. One trial = one file (switch on -> off).

For every trial it prints the algorithm's breath count and rate next to the hand counts, the
percent error (Appendix B) and whether it meets the 5% target, plus trial-validity checks.

1. Make a counts sheet for the counters to fill in (one row per trial file):
       python trial_report.py TRIALS_FOLDER --make-counts-template counts.csv
2. Counters fill counter_1 / counter_2 with complete breaths counted switch-on to switch-off.
3. Run the report (writes a CSV you can paste into the memo):
       python trial_report.py TRIALS_FOLDER --counts counts.csv --out results.csv

Settling: the first seconds after switch-on (belt being fastened, volunteer settling) and the
last seconds before switch-off aren't breathing. Use --trim-start / --trim-end to skip them,
and have the counters count the SAME window (start counting when the trim ends).

Error is computed on whole-trial breath counts. For a fixed duration that's the same as the
error on breaths/min, and it avoids the +/-1 breath jump that a single 60 s window has.
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

import numpy as np

from processing.filters import remove_glitches
from processing.load import load_trial
from processing.metrics import percent_error
from processing.pipeline import process_trial
from processing.quality import GOOD_SIR_DB, GOOD_SNR_DB

TARGET_ERROR_PCT = 5.0
MIN_TRIAL_S = 160.0  # 10 s settling + 2 min breathing + 10 s hold + margin
MAX_REMOVED_FRACTION = 0.2
RECORDING_NAME = re.compile(r"^S\d{8}_\d{6}(_[^\\/]+)?\.csv$", re.IGNORECASE)
FIELDS = [
    "file", "label", "duration_s", "window_s", "stop_reason", "missed_samples",
    "algo_breaths", "algo_rate_bpm", "snr_db", "sir_db", "counter_1", "counter_2", "counted_mean",
    "error_pct", "meets_target", "notes",
]  # fmt: skip


def find_trials(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for p in paths:
        if p.is_dir():
            files += sorted(f for f in p.iterdir() if RECORDING_NAME.match(f.name))
        else:
            files.append(p)
    return files


def read_counts(path: Path) -> dict[str, tuple[float | None, float | None]]:
    out = {}
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):

            def num(v: str | None) -> float | None:
                return float(v) if v not in (None, "") else None

            out[row["file"]] = (num(row.get("counter_1")), num(row.get("counter_2")))
    return out


def analyse(
    path: Path,
    counts: tuple[float | None, float | None],
    trim_start_s: float = 0.0,
    trim_end_s: float = 0.0,
) -> dict[str, object]:
    trial = load_trial(path)
    notes: list[str] = []
    if trial.stop_reason != "switch":
        notes.append(
            f"stopped by '{trial.stop_reason}'" if trial.stop_reason else "ended unexpectedly"
        )
    if trial.duration_s < MIN_TRIAL_S:
        notes.append(f"shorter than {MIN_TRIAL_S:.0f} s")
    if trial.missed_samples:
        notes.append(f"{trial.missed_samples} missed samples")
    if np.isfinite(trial.L_uH).any():
        removed = 1 - np.isfinite(remove_glitches(trial.L_uH, trial.fs_hz)).mean()
        if removed > MAX_REMOVED_FRACTION:
            notes.append(
                f"sensor unreliable: {removed:.0%} of readings removed (stuck or glitching)"
            )

    row: dict[str, object] = {
        "file": path.name,
        "label": trial.label,
        "duration_s": round(trial.duration_s, 1),
        "stop_reason": trial.stop_reason or "",
        "missed_samples": trial.missed_samples,
        "counter_1": counts[0] if counts[0] is not None else "",
        "counter_2": counts[1] if counts[1] is not None else "",
    }
    try:
        result = process_trial(trial, trim_start_s=trim_start_s, trim_end_s=trim_end_s)
        row["window_s"] = f"{result.window_s[0]:.0f}-{result.window_s[1]:.0f}"
        row["algo_breaths"] = result.breath_count
        row["algo_rate_bpm"] = round(result.rate_bpm, 2)
        row["snr_db"] = round(result.snr_db, 1)
        row["sir_db"] = round(result.sir_db, 1)
        if result.snr_db < GOOD_SNR_DB or result.sir_db < GOOD_SIR_DB:
            notes.append("low signal quality (SNR/SIR below target): check belt fit")
    except (NotImplementedError, ValueError) as err:
        row["algo_breaths"] = row["algo_rate_bpm"] = row["window_s"] = ""
        row["snr_db"] = row["sir_db"] = ""
        notes.append(str(err))

    given = [c for c in counts if c is not None]
    if given:
        mean = sum(given) / len(given)
        row["counted_mean"] = round(mean, 2)
        if len(given) == 2 and abs(given[0] - given[1]) > 1:
            notes.append("counters disagree by more than 1 breath: recount from video")
        if row["algo_breaths"] != "":
            err = percent_error(float(row["algo_breaths"]), mean)
            row["error_pct"] = round(err, 2)
            row["meets_target"] = "yes" if err <= TARGET_ERROR_PCT else "NO"
    row["notes"] = "; ".join(notes)
    return row


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Test 2 breathing-accuracy report.")
    parser.add_argument("trials", type=Path, nargs="+", help="trial CSV files or folders of them")
    parser.add_argument("--counts", type=Path, help="CSV with columns file,counter_1,counter_2")
    parser.add_argument("--out", type=Path, help="write the results table as CSV")
    parser.add_argument(
        "--trim-start",
        type=float,
        default=0.0,
        metavar="S",
        help="skip this many seconds after switch-on (belt settling)",
    )
    parser.add_argument(
        "--trim-end",
        type=float,
        default=0.0,
        metavar="S",
        help="skip this many seconds before switch-off",
    )
    parser.add_argument(
        "--make-counts-template",
        type=Path,
        metavar="CSV",
        help="write an empty counts sheet for these trials and stop",
    )
    args = parser.parse_args(argv)

    files = find_trials(args.trials)
    if not files:
        parser.error("no trial files found (expected names like S20261110_140000_P03-lying-t1.csv)")

    if args.make_counts_template:
        with args.make_counts_template.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["file", "counter_1", "counter_2"])
            w.writerows([[p.name, "", ""] for p in files])
        print(f"Wrote {args.make_counts_template} with {len(files)} trial(s) to fill in.")
        return 0

    counts = read_counts(args.counts) if args.counts else {}
    rows = [
        analyse(p, counts.get(p.name, (None, None)), args.trim_start, args.trim_end) for p in files
    ]

    for r in rows:
        algo = f"{r['algo_breaths']!s:>5} breaths {r['algo_rate_bpm']!s:>6}/min"
        algo += f"  SNR {r.get('snr_db', '')!s:>5} SIR {r.get('sir_db', '')!s:>5} dB"
        hand = f"counted {r.get('counted_mean', '')!s:>6}"
        score = f"error {r.get('error_pct', '')!s:>6}% {r.get('meets_target', '')}"
        print(f"{r['file']:<40} {algo}  {hand}  {score}  {r['notes']}")
    scored = [r for r in rows if r.get("error_pct") not in (None, "")]
    if scored:
        mean_err = sum(float(r["error_pct"]) for r in scored) / len(scored)
        passed = sum(r["meets_target"] == "yes" for r in scored)
        print(f"\n{len(scored)} scored trial(s): mean error {mean_err:.2f}%,")
        print(f"{passed} within the {TARGET_ERROR_PCT:g}% target")

    if args.out:
        with args.out.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(rows)
        print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
