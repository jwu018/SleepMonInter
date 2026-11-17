"""Validation: run the algorithm on every synthetic night and compare with the ground truth.

    python validate.py                 # all nights in ../sample_data, writes ../docs/VALIDATION.md
    python validate.py --limit 1       # just the first night of each profile (quick check)

The synthetic generator knows the true answer for every minute (`*.truth.json`), so this
measures the algorithm itself. The design target is breathing rate within 5%.

What is compared, per night:
- rate:      per-minute breaths/min, on minutes the truth calls good or poor (not no_signal)
- amplitude: per-minute mean breath depth relative to the night's median
- quality:   the algorithm's good / poor / no_signal label against the truth's label
- pauses:    true pauses longer than 10 s that the algorithm reports, and false reports
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from processing.load import load_trial
from processing.metrics import (
    amplitude_per_minute,
    find_pauses,
    median_breath_depth,
    respiratory_rate_per_minute,
)
from processing.pipeline import process_trial

REPO = Path(__file__).resolve().parents[1]
SAMPLE_DATA = REPO / "sample_data"
REAL_BELT = REPO / "irl_sample_data" / "S20261029_134821_14-17in.csv"
TARGET_PCT = 5.0
LABELS = ("good", "poor", "no_signal")
# Truth events during which a "pause" report is expected or excusable (the belt shows no breathing).
FLAT_EVENTS = ("pause", "no_signal", "data_gap")


@dataclass
class NightResult:
    recording_id: str
    profile: str
    rate_error_pct: dict[str, np.ndarray]  # truth label -> |error| % per minute with a rate
    rate_bias_bpm: dict[str, np.ndarray]  # truth label -> signed error (algorithm - truth)
    coverage: dict[str, tuple[int, int]]  # truth label -> (minutes with a rate, minutes)
    amplitude_error: np.ndarray  # |algorithm - truth| on good minutes
    confusion: np.ndarray  # [truth label][algorithm label] minute counts
    pauses_true: int = 0
    pauses_found: int = 0
    pauses_false: int = 0
    notes: list[str] = field(default_factory=list)


def overlaps(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def validate_night(csv_path: Path, truth_path: Path, recording_id: str) -> NightResult:
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    minutes = truth["minutes"]
    true_rate = np.array([np.nan if v is None else v for v in minutes["resp_rate_bpm"]])
    true_amp = np.array([np.nan if v is None else v for v in minutes["amplitude_rel"]])
    true_label = np.array(minutes["quality"])

    trial = load_trial(csv_path)
    result = process_trial(trial)
    fs = trial.fs_hz
    n = min(len(true_rate), int(len(trial.t_s) // (60 * fs)))
    true_rate, true_amp, true_label = true_rate[:n], true_amp[:n], true_label[:n]
    rate = respiratory_rate_per_minute(result.breaths, fs, len(trial.t_s))[:n]
    amp = amplitude_per_minute(result.filtered, result.breaths, fs, n)
    algo_label = np.array([w.label for w in result.quality][:n])

    error_pct, bias, coverage = {}, {}, {}
    for label in ("good", "poor"):
        of_label = (true_label == label) & (true_rate > 0)
        both = of_label & np.isfinite(rate)
        error_pct[label] = 100 * np.abs(rate[both] - true_rate[both]) / true_rate[both]
        bias[label] = rate[both] - true_rate[both]
        coverage[label] = (int(both.sum()), int(of_label.sum()))

    good = (true_label == "good") & np.isfinite(amp) & np.isfinite(true_amp)
    confusion = np.array(
        [[int(((true_label == t) & (algo_label == a)).sum()) for a in LABELS] for t in LABELS]
    )

    out = NightResult(
        recording_id, truth["profile"], error_pct, bias, coverage,
        np.abs(amp[good] - true_amp[good]), confusion,
    )  # fmt: skip

    events = [(e["kind"], e["start_ms"] / 1000, e["end_ms"] / 1000) for e in truth["events"]]
    flat = [(s, e) for kind, s, e in events if kind in FLAT_EVENTS]
    # Back-to-back pauses are one long pause on the belt, so merge them before counting.
    true_pauses: list[tuple[float, float]] = []
    for s, e in sorted((s, e) for kind, s, e in events if kind == "pause"):
        if true_pauses and s - true_pauses[-1][1] < 1.0:
            true_pauses[-1] = (true_pauses[-1][0], e)
        else:
            true_pauses.append((s, e))
    # A true pause "counts" only if no data is missing inside it (the belt could see it).
    lost = [(s, e) for kind, s, e in events if kind in ("no_signal", "data_gap")]
    long_pauses = [
        p for p in true_pauses if p[1] - p[0] > 11.0 and not any(overlaps(p, g) for g in lost)
    ]
    found = find_pauses(result.cleaned, median_breath_depth(result.filtered, result.breaths), fs)
    out.pauses_true = len(long_pauses)
    out.pauses_found = sum(any(overlaps(p, f) for f in found) for p in long_pauses)
    out.pauses_false = sum(not any(overlaps(f, (s - 2, e + 2)) for s, e in flat) for f in found)
    return out


def pct(part: float, whole: float) -> str:
    return f"{100 * part / whole:.1f}" if whole else "-"


def summarise(profile: str, nights: list[NightResult]) -> dict[str, list[object]]:
    """One table row per section for a profile (all its nights pooled)."""

    def pooled(get) -> np.ndarray:
        return np.concatenate([get(nt) for nt in nights])

    rows: dict[str, list[object]] = {}
    for label in ("good", "poor"):
        err = pooled(lambda nt, label=label: nt.rate_error_pct[label])
        bias = pooled(lambda nt, label=label: nt.rate_bias_bpm[label])
        got = sum(nt.coverage[label][0] for nt in nights)
        total = sum(nt.coverage[label][1] for nt in nights)
        if len(err) == 0:
            rows[f"rate_{label}"] = [profile, total, "-", "-", "-", "-", "-"]
            continue
        rows[f"rate_{label}"] = [
            profile,
            total,
            pct(got, total),
            f"{np.median(err):.2f}",
            f"{np.percentile(err, 95):.1f}",
            pct((err <= TARGET_PCT).sum(), len(err)),
            f"{np.mean(bias):+.2f}",
        ]
    amp = pooled(lambda nt: nt.amplitude_error)
    rows["amplitude"] = [
        profile,
        len(amp),
        f"{np.median(amp):.3f}",
        f"{np.percentile(amp, 95):.2f}",
        pct((amp <= 0.1).sum(), len(amp)),
    ]
    confusion = sum(nt.confusion for nt in nights)
    rows["quality"] = [
        profile,
        *[f"{confusion[i][0]} / {confusion[i][1]} / {confusion[i][2]}" for i in range(len(LABELS))],
    ]
    true = sum(nt.pauses_true for nt in nights)
    rows["pauses"] = [
        profile,
        true,
        sum(nt.pauses_found for nt in nights),
        pct(sum(nt.pauses_found for nt in nights), true),
        sum(nt.pauses_false for nt in nights),
    ]
    return rows


def table(headers: list[str], rows: list[list[object]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(str(v) for v in row) + " |" for row in rows]
    return "\n".join(lines)


def belt_section() -> str:
    if not REAL_BELT.exists():
        return ""
    trial = load_trial(REAL_BELT)
    r = process_trial(trial, trim_start_s=10, trim_end_s=5)
    return (
        "## Real belt recording\n\n"
        f"`{REAL_BELT.name}` (a teammate breathing normally, counted 10 s after switch-on to 5 s"
        " before switch-off):\n\n"
        + table(
            ["breaths visible by eye", "algorithm", "rate (/min)", "SNR (dB)", "SIR (dB)"],
            [[27, r.breath_count, f"{r.rate_bpm:.1f}", f"{r.snr_db:.1f}", f"{r.sir_db:.1f}"]],
        )
        + "\n\nThis is one short recording with an informal count; Test 2 gives the real"
        " comparison against two hand counters.\n"
    )


def report(by_profile: dict[str, list[NightResult]]) -> str:
    summaries = [summarise(profile, nights) for profile, nights in by_profile.items()]
    n_nights = sum(len(v) for v in by_profile.values())
    rate_headers = [
        "profile",
        "minutes",
        "minutes with a rate (%)",
        "median error (%)",
        "95th percentile error (%)",
        f"within {TARGET_PCT:.0f}% (% of minutes)",
        "mean bias (/min)",
    ]
    return "\n\n".join(
        [
            "# Validation against synthetic ground truth\n\n"
            "Generated by `tools/validate.py`. Do not edit by hand; rerun the script instead.\n\n"
            f"{n_nights} synthetic nights, compared minute by minute with the generator's ground"
            " truth. Limits and what they mean are discussed in `docs/FILTERING.md`.",
            "## Breathing rate, minutes the truth calls **good**\n\n"
            + table(rate_headers, [s["rate_good"] for s in summaries]),
            "## Breathing rate, minutes the truth calls **poor** (an artifact, gap or loose band"
            " touches the minute)\n\n" + table(rate_headers, [s["rate_poor"] for s in summaries]),
            "## Relative amplitude, good minutes\n\n"
            "Error is in units of relative amplitude (1.0 = a typical breath).\n\n"
            + table(
                ["profile", "minutes", "median error", "95th percentile error", "within 0.1 (%)"],
                [s["amplitude"] for s in summaries],
            ),
            "## Quality labels\n\n"
            "Each cell: minutes the algorithm labelled good / poor / no_signal.\n\n"
            + table(
                ["profile", "truth: good", "truth: poor", "truth: no_signal"],
                [s["quality"] for s in summaries],
            ),
            "## Breathing pauses longer than 10 s\n\n"
            "True pauses of 11 s or more with no data missing inside them. A false report is a"
            " reported pause that overlaps no true pause, loose-band stretch or data gap.\n\n"
            + table(
                ["profile", "true pauses", "found", "found (%)", "false reports"],
                [s["pauses"] for s in summaries],
            ),
            belt_section(),
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare the algorithm with synthetic truth.")
    parser.add_argument("--limit", type=int, help="only the first N nights of each profile")
    parser.add_argument("--out", type=Path, default=REPO / "docs" / "VALIDATION.md")
    args = parser.parse_args(argv)

    manifest = json.loads((SAMPLE_DATA / "manifest.json").read_text(encoding="utf-8"))
    by_profile: dict[str, list[NightResult]] = {}
    for rec in manifest["recordings"]:
        nights = by_profile.setdefault(rec["profile"], [])
        if args.limit and len(nights) >= args.limit:
            continue
        csv_path = SAMPLE_DATA / rec["csv"]
        if not csv_path.exists():
            print(f"Missing {csv_path}: run `python generate_sample_set.py` first")
            return 1
        print(f"{rec['recording_id']} ({rec['profile']}) ...", flush=True)
        nights.append(validate_night(csv_path, SAMPLE_DATA / rec["truth"], rec["recording_id"]))

    text = report(by_profile)
    args.out.write_text(text + "\n", encoding="utf-8")
    print(f"\n{text}\n\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
