"""Filter-parameter study: what each processing parameter keeps, removes and costs.

Answers "are we filtering away real information to make the signal look clean?" with
measurements instead of opinion. It writes figures and one markdown file of tables:

    python filter_study.py                      # -> ../docs/figures/filtering/
    python filter_study.py --out some/folder

Sections (each is one function below):
    1. frequency_response   which breathing rates the band-pass keeps, and how much of each
    2. what_is_removed      the real belt recording split into kept / removed parts
    3. rejected_readings    how many readings glitch removal throws away, per file
    4. rate_range           true rate 4-80 breaths/min -> what the algorithm reports
    5. sensitivity          breath-count error when each parameter is changed
    6. time_resolution      the same breathing seen through different rate windows
    7. events               pause, posture step, sigh, waxing/waning depth through the filter
    8. phase                zero-phase (filtfilt) vs an ordinary one-pass filter

This is analysis tooling. It never changes the algorithm's defaults; it only measures them.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # write PNG files; never open a window
import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import butter, sosfilt, sosfreqz, welch

from generate_synthetic import (
    BREATH_AMPLITUDE_UH,
    INHALE_FRACTION,
    PROFILES,
    BreathSchedule,
    SyntheticNight,
    render_breathing,
    simulate_night,
    slow_wave,
)
from processing.breaths import Breaths, detect_breaths
from processing.filters import VALID_RANGE_UH, _blank_stuck_runs, bandpass, remove_glitches
from processing.load import fill_short_gaps, load_trial
from processing.metrics import (
    _breath_count_at,
    count_complete_breaths,
    find_pauses,
    median_breath_depth,
)
from processing.pipeline import breaths_in_window

FS = 25.0
REPO = Path(__file__).resolve().parents[1]
REAL_DIR = REPO / "irl_sample_data"
REAL_BELT = REAL_DIR / "S20261029_134821_14-17in.csv"
BELT_TRIM_S = (10.0, 5.0)  # settling after switch-on / handling before switch-off
BELT_VISIBLE_BREATHS = 27  # counted by eye on the plot (see docs/PROGRESS.md, 2026-11-10)

# The values the algorithm uses today. Every sweep changes ONE of these at a time.
DEFAULTS = {
    "low_hz": 0.1,
    "high_hz": 1.0,
    "order": 2,
    "prominence_fraction": 0.15,
    "min_period_s": 1.0,
}
SWEEPS = {
    "low_hz": [0.03, 0.05, 0.1, 0.15, 0.2, 0.3],
    "high_hz": [0.5, 0.7, 1.0, 1.5, 2.0, 3.0],
    "order": [1, 2, 4],
    "prominence_fraction": [0.05, 0.1, 0.15, 0.2, 0.3, 0.4],
    "min_period_s": [0.75, 1.0, 1.5, 2.0, 2.5],
}
LABELS = {
    "low_hz": "Band-pass low cutoff (Hz)",
    "high_hz": "Band-pass high cutoff (Hz)",
    "order": "Filter order (per pass)",
    "prominence_fraction": "Peak prominence (fraction of breath size)",
    "min_period_s": "Minimum time between breaths (s)",
}


# --- Helpers ------------------------------------------------------------------------------


@dataclass
class Analysis:
    cleaned: np.ndarray
    filtered: np.ndarray
    breaths: Breaths


def analyse(L_uH: np.ndarray, fs: float = FS, **overrides: float) -> Analysis:
    """The same chain as pipeline.process_trial, but with every parameter adjustable."""
    p = {**DEFAULTS, **overrides}
    cleaned = fill_short_gaps(remove_glitches(L_uH, fs), fs)
    filtered = bandpass(cleaned, fs, p["low_hz"], p["high_hz"], order=int(p["order"]))
    breaths = detect_breaths(
        filtered,
        fs,
        min_period_s=p["min_period_s"],
        prominence_fraction=p["prominence_fraction"],
    )
    return Analysis(cleaned, filtered, breaths)


def night_to_grid(night: SyntheticNight) -> np.ndarray:
    """Synthetic samples on the even 25 Hz grid (NaN where the generator dropped samples)."""
    grid = np.full(int(night.sample_idx[-1]) + 1, np.nan)
    grid[night.sample_idx] = night.L_uH
    return grid


def true_complete_breaths(schedule: BreathSchedule, start_s: float, end_s: float) -> int:
    inside = (schedule.start_s >= start_s) & (schedule.start_s + schedule.duration_s <= end_s)
    return int((schedule.is_breath & inside).sum())


def build_schedule(
    duration_s: float,
    rate_bpm_at: Callable[[float], float],
    amplitude_at: Callable[[float], float] = lambda t: 1.0,
    pauses: tuple[tuple[float, float], ...] = (),
    jitter: float = 0.0,
    rng: np.random.Generator | None = None,
) -> BreathSchedule:
    """Breaths back to back with a rate and depth we choose exactly (pauses = (start, length))."""
    starts, durations, amplitudes, is_breath = [], [], [], []
    todo = sorted(pauses)
    t = 0.0
    while t < duration_s:
        if todo and t >= todo[0][0]:
            length = todo.pop(0)[1]
            starts.append(t), durations.append(length), amplitudes.append(0.0)
            is_breath.append(False)
            t += length
            continue
        period = 60.0 / rate_bpm_at(t)
        if jitter and rng is not None:
            period *= 1 + jitter * rng.standard_normal()
        starts.append(t), durations.append(period)
        amplitudes.append(BREATH_AMPLITUDE_UH * amplitude_at(t))
        is_breath.append(True)
        t += period
    return BreathSchedule(
        np.array(starts), np.array(durations), np.array(amplitudes), np.array(is_breath)
    )


def render(
    schedule: BreathSchedule,
    duration_s: float,
    rng: np.random.Generator,
    noise_rel: float = 0.03,
    wander_rel: float = 0.4,
) -> tuple[np.ndarray, np.ndarray]:
    """(t_s, L_uH): the schedule as a belt signal with the stable profile's noise and drift."""
    t = np.arange(int(duration_s * FS)) / FS
    wander = wander_rel * BREATH_AMPLITUDE_UH * slow_wave(rng, t, (5 * 60, 30 * 60))
    noise = rng.normal(0, noise_rel * BREATH_AMPLITUDE_UH, len(t))
    return t, 4.1 + render_breathing(schedule, t) + wander + noise


def windowed_rate(breaths: Breaths, fs: float, centres_s: np.ndarray, width_s: float) -> np.ndarray:
    """Breaths/min in a window of `width_s` centred on each time (NaN if it leaves the data).

    Same counting rule as metrics.respiratory_rate_per_minute: fractional breaths between
    exhale troughs, so only the window length differs between the curves we compare.
    """
    trough_s = breaths.trough_times_s(fs)
    out = np.full(len(centres_s), np.nan)
    if len(trough_s) < 2:
        return out
    a, b = centres_s - width_s / 2, centres_s + width_s / 2
    ok = (a >= trough_s[0]) & (b <= trough_s[-1])
    out[ok] = (_breath_count_at(b[ok], trough_s) - _breath_count_at(a[ok], trough_s)) / width_s * 60
    return out


def breath_by_breath(breaths: Breaths, fs: float) -> tuple[np.ndarray, np.ndarray]:
    t = breaths.trough_times_s(fs)
    return (t[1:] + t[:-1]) / 2, 60.0 / np.diff(t)


def true_peak_times(schedule: BreathSchedule) -> np.ndarray:
    return (schedule.start_s + INHALE_FRACTION * schedule.duration_s)[schedule.is_breath]


def detection_errors(
    detected_s: np.ndarray, true_s: np.ndarray, tolerance_s: float = 0.75
) -> tuple[int, int]:
    """(missed, extra): pair each true breath with one detected peak within `tolerance_s`.

    Stricter than comparing totals: a missed breath and a fake breath cannot cancel out.
    """
    used = np.zeros(len(detected_s), dtype=bool)
    missed = 0
    for t in true_s:
        near = np.flatnonzero(~used & (np.abs(detected_s - t) <= tolerance_s))
        if len(near):
            used[near[np.abs(detected_s[near] - t).argmin()]] = True
        else:
            missed += 1
    return missed, int((~used).sum())


def pauses_old_rule(breaths: Breaths, min_pause_s: float = 10.0) -> list[tuple[float, float]]:
    """The rule used until 2026-11-16: > 10 s between filtered turning points."""
    turning = np.sort(np.concatenate([breaths.peak_idx, breaths.trough_idx])) / FS
    return [
        (float(turning[i]), float(turning[i + 1]))
        for i in np.flatnonzero(np.diff(turning) > min_pause_s)
    ]


def pauses_new_rule(a: Analysis) -> list[tuple[float, float]]:
    return find_pauses(a.cleaned, median_breath_depth(a.filtered, a.breaths), FS)


def table(headers: list[str], rows: list[list[object]]) -> str:
    def cell(v: object) -> str:
        return f"{v:.2f}" if isinstance(v, float) else str(v)

    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(cell(v) for v in row) + " |" for row in rows]
    return "\n".join(lines)


def save(fig: plt.Figure, out: Path, name: str) -> str:
    fig.tight_layout()
    fig.savefig(out / name, dpi=130)
    plt.close(fig)
    return name


# --- 1. Frequency response ----------------------------------------------------------------


def zero_phase_gain(low_hz: float, high_hz: float, order: int, freqs_hz: np.ndarray) -> np.ndarray:
    """Amplitude kept at each frequency. filtfilt applies the filter twice, so gain = |H|^2."""
    sos = butter(order, [low_hz, high_hz], btype="bandpass", fs=FS, output="sos")
    _, h = sosfreqz(sos, worN=freqs_hz, fs=FS)
    return np.abs(h) ** 2


def frequency_response(out: Path) -> str:
    bpm = np.logspace(np.log10(2), np.log10(150), 600)
    fig, ax = plt.subplots(figsize=(10, 4.8))
    ax.axvspan(12, 30, color="tab:green", alpha=0.12, label="expected sleeping rates (12-30/min)")
    for (low, high), style in {
        (0.1, 1.0): {"color": "tab:blue", "lw": 2.5, "label": "used: 0.1-1.0 Hz"},
        (0.05, 1.0): {"color": "tab:orange", "ls": "--", "label": "0.05-1.0 Hz"},
        (0.1, 2.0): {"color": "tab:red", "ls": "--", "label": "0.1-2.0 Hz"},
        (0.2, 0.7): {"color": "gray", "ls": ":", "label": "0.2-0.7 Hz (too narrow)"},
    }.items():
        ax.plot(bpm, 100 * zero_phase_gain(low, high, 2, bpm / 60), **style)
    ax.axhline(95, color="k", lw=0.6, ls=":")
    ax.set_xscale("log")
    ticks = [2, 4, 6, 10, 15, 20, 30, 40, 60, 100, 150]
    ax.set_xticks(ticks, [str(v) for v in ticks])
    ax.set_xlabel("breathing rate (breaths/min)")
    ax.set_ylabel("breath depth kept (%)")
    ax.set_title("How much of a breath's size the band-pass filter keeps, by breathing rate")
    ax.legend(loc="lower center", fontsize=8)
    name = save(fig, out, "1_frequency_response.png")

    rates = [4, 6, 8, 10, 12, 15, 20, 30, 40, 50, 60, 80]
    gain = 100 * zero_phase_gain(0.1, 1.0, 2, np.array(rates) / 60)
    dense = np.linspace(2, 150, 5000)
    kept = 100 * zero_phase_gain(0.1, 1.0, 2, dense / 60)
    flat = dense[kept >= 95]
    half = dense[kept >= 50]
    return (
        f"## 1. Which breathing rates the band-pass keeps\n\n![]({name})\n\n"
        + table(["breaths/min", *[str(r) for r in rates]], [["depth kept (%)", *gain.round(0)]])
        + f"\n\n- At least 95% of the depth is kept from **{flat[0]:.0f} to {flat[-1]:.0f}"
        f" breaths/min**; at least 50% from {half[0]:.0f} to {half[-1]:.0f}.\n"
    )


# --- 2. What is removed (real belt) -------------------------------------------------------


def band_power_share(cleaned: np.ndarray) -> tuple[np.ndarray, np.ndarray, list[float]]:
    x = cleaned[np.isfinite(cleaned)]
    f, pxx = welch(x - np.median(x), fs=FS, nperseg=min(len(x), int(60 * FS)))
    total = np.trapezoid(pxx, f)
    share = [
        100 * np.trapezoid(pxx[m], f[m]) / total
        for m in (f < 0.1, (f >= 0.1) & (f <= 1.0), f > 1.0)
    ]
    return f, pxx, share


def what_is_removed(out: Path) -> str:
    trial = load_trial(REAL_BELT)
    a = analyse(trial.L_uH, trial.fs_hz)
    t = trial.t_s
    centred = a.cleaned - np.nanmedian(a.cleaned)
    removed = centred - a.filtered
    rejected = np.isfinite(trial.L_uH) & ~np.isfinite(remove_glitches(trial.L_uH, trial.fs_hz))

    fig, axes = plt.subplots(3, 1, figsize=(12, 8), sharex=True)
    axes[0].plot(t, trial.L_uH, lw=0.8, color="gray")
    axes[0].plot(t[rejected], trial.L_uH[rejected], "x", color="tab:red", label="rejected reading")
    axes[0].set_ylabel("raw inductance (uH)")
    axes[0].set_title(f"{REAL_BELT.name}: raw -> kept -> removed (same vertical scale below)")
    if rejected.any():
        axes[0].legend(fontsize=8)
    axes[1].plot(t, a.filtered, lw=0.9, color="tab:blue")
    b = a.breaths
    axes[1].plot(b.peak_idx / FS, a.filtered[b.peak_idx], "v", color="tab:red", ms=4)
    axes[1].plot(b.trough_idx / FS, a.filtered[b.trough_idx], "^", color="tab:green", ms=4)
    axes[1].set_ylabel("KEPT: 0.1-1 Hz (uH)")
    axes[2].plot(t, removed, lw=0.8, color="tab:orange")
    axes[2].set_ylabel("REMOVED: raw - kept (uH)")
    axes[2].set_xlabel("seconds since switch-on")
    lim = np.nanmax(np.abs(np.concatenate([a.filtered, removed]))) * 1.05
    for ax in axes[1:]:
        ax.set_ylim(-lim, lim)
        for edge in (BELT_TRIM_S[0], trial.duration_s - BELT_TRIM_S[1]):
            ax.axvline(edge, color="k", lw=0.6, ls=":")
    name_a = save(fig, out, "2_what_is_removed.png")

    f, pxx, share = band_power_share(a.cleaned)
    fig, ax = plt.subplots(figsize=(10, 4.2))
    ax.semilogy(f * 60, pxx, color="tab:blue")
    ax.axvspan(6, 60, color="tab:green", alpha=0.12, label="kept band (6-60 /min)")
    ax.set_xlim(0, 180)
    ax.set_xlabel("frequency, written as breaths/min")
    ax.set_ylabel("power (uH^2/Hz)")
    ax.set_title("Where the belt signal's power sits (real recording, before filtering)")
    ax.legend(fontsize=8)
    name_b = save(fig, out, "3_spectrum.png")

    start, end = int(BELT_TRIM_S[0] * FS), int((trial.duration_s - BELT_TRIM_S[1]) * FS)
    kept_std = np.nanstd(a.filtered[start:end])
    removed_std = np.nanstd(removed[start:end])
    return (
        f"## 2. What the filter removes from a real belt recording\n\n![]({name_a})\n\n"
        f"![]({name_b})\n\n"
        + table(
            ["part of the signal", "share of power (%)"],
            [
                ["slower than 0.1 Hz (drift, settling)", share[0]],
                ["0.1-1 Hz (kept)", share[1]],
                ["faster than 1 Hz (noise)", share[2]],
            ],
        )
        + f"\n\n- Readings rejected as glitches in this file: {int(rejected.sum())} of"
        f" {int(np.isfinite(trial.L_uH).sum())}.\n"
        f"- Inside the counting window the kept signal's spread (std) is {kept_std * 1000:.1f} nH;"
        f" the removed part's is {removed_std * 1000:.1f} nH.\n"
    )


# --- 3. Rejected readings -----------------------------------------------------------------


def glitch_breakdown(L_uH: np.ndarray, fs: float) -> dict[str, float]:
    """Percent of sensor readings removed by each check, in the order the checks run."""
    had = np.isfinite(L_uH)
    n = max(int(had.sum()), 1)
    x = np.asarray(L_uH, dtype=float).copy()
    _blank_stuck_runs(x, int(round(0.5 * fs)))
    stuck = had & ~np.isfinite(x)
    out_of_range = np.isfinite(x) & ((x < VALID_RANGE_UH[0]) | (x > VALID_RANGE_UH[1]))
    final = np.isfinite(remove_glitches(L_uH, fs))
    spike = had & ~final & ~stuck & ~out_of_range
    return {
        "stuck": 100 * stuck.sum() / n,
        "out_of_range": 100 * out_of_range.sum() / n,
        "spike": 100 * spike.sum() / n,
        "total": 100 * (had & ~final).sum() / n,
    }


def rejected_readings() -> str:
    rows = []
    for path in sorted(REAL_DIR.glob("S*.csv")):
        trial = load_trial(path)
        if not np.isfinite(trial.L_uH).any():
            continue
        g = glitch_breakdown(trial.L_uH, trial.fs_hz)
        rows.append(
            [
                path.stem,
                round(trial.duration_s),
                g["stuck"],
                g["out_of_range"],
                g["spike"],
                g["total"],
            ]
        )
    for name in ("stable", "noisy"):
        night = simulate_night(PROFILES[name], 3600.0, np.random.default_rng(7))
        g = glitch_breakdown(night_to_grid(night), FS)
        rows.append(
            [f"synthetic {name}, 1 h", 3600, g["stuck"], g["out_of_range"], g["spike"], g["total"]]
        )
    return (
        "## 3. How many readings glitch removal rejects\n\n"
        "Percent of that file's sensor readings. Rejected readings become gaps; gaps longer"
        " than 2 s stay visible as gaps and are never filled in.\n\n"
        + table(
            ["recording", "length (s)", "stuck (%)", "out of range (%)", "spike (%)", "total (%)"],
            rows,
        )
        + "\n"
    )


# --- 4. Rate range ------------------------------------------------------------------------


def rate_range(out: Path) -> str:
    rates = [4, 5, 6, 8, 10, 12, 15, 20, 25, 30, 35, 40, 45, 50, 60, 80]
    rows, found = [], {}
    for min_period in (DEFAULTS["min_period_s"], 1.5, 0.75):
        found[min_period] = []
        for rate in rates:
            rng = np.random.default_rng(rate)
            duration = 300.0
            schedule = build_schedule(duration, lambda t, r=rate: r, jitter=0.03, rng=rng)
            _, L = render(schedule, duration, rng)
            a = analyse(L, min_period_s=min_period)
            window = (20.0, duration - 20.0)
            got = count_complete_breaths(breaths_in_window(a.breaths, FS, *window), len(L))
            reported = got / ((window[1] - window[0]) / 60)
            found[min_period].append(reported)
            if min_period == DEFAULTS["min_period_s"]:
                p, tr = a.breaths.peak_idx, a.breaths.trough_idx
                k = min(len(p), len(tr))
                depth = np.median(np.abs(a.filtered[p[:k]] - a.filtered[tr[:k]])) if k else np.nan
                rows.append([rate, reported, 100 * (reported - rate) / rate, 100 * depth / 0.06])

    fig, ax = plt.subplots(figsize=(7.5, 5.5))
    ax.plot(rates, rates, color="k", lw=0.8, label="perfect")
    for min_period, style in zip(found, ("o-", "s--", "^:"), strict=True):
        ax.plot(rates, found[min_period], style, ms=4, label=f"min gap {min_period} s")
    ax.set_xlabel("true breathing rate (breaths/min)")
    ax.set_ylabel("rate the algorithm reports (breaths/min)")
    ax.set_title("Measurable range: true rate vs reported rate (5-minute steady breathing)")
    ax.legend(fontsize=8)
    name = save(fig, out, "4_rate_range.png")
    return (
        f"## 4. The range of rates the algorithm can measure\n\n![]({name})\n\n"
        f"With today's settings (min gap {DEFAULTS['min_period_s']} s):\n\n"
        + table(["true rate (/min)", "reported (/min)", "error (%)", "depth kept (%)"], rows)
        + "\n"
    )


# --- 5. Sensitivity -----------------------------------------------------------------------


SENSITIVITY_WINDOW_S = (10.0, 170.0)  # ignore the first/last 10 s (file-edge effects)


def sensitivity_trials() -> dict[str, list[tuple[np.ndarray, np.ndarray]]]:
    """Four sets of 3-minute synthetic trials: (signal, true inhale-peak times)."""
    quiet = {
        "artifacts_per_hour": 0,
        "no_signal_per_hour": 0,
        "gaps_per_hour": 0,
        "pauses_per_hour": 0,
        "shallow_per_hour": 0,
    }
    profiles = {
        "clean": replace(PROFILES["stable"], **quiet),
        "fast (26-30/min)": replace(PROFILES["stable"], **quiet, rr_start_bpm=(26.0, 30.0)),
        # Spells of breathing at 30-60% of the usual depth (about 2 per trial, 1-5 min long).
        "shallow spells": replace(PROFILES["stable"], **{**quiet, "shallow_per_hour": 40}),
        # ~3 artifacts and one pause per 3-minute trial, 10% noise, strong drift.
        "restless": replace(
            PROFILES["noisy"],
            artifacts_per_hour=60,
            pauses_per_hour=20,
            no_signal_per_hour=0,
            gaps_per_hour=0,
            shallow_per_hour=0,
        ),
    }
    sets: dict[str, list[tuple[np.ndarray, np.ndarray]]] = {}
    for name, profile in profiles.items():
        sets[name] = []
        for seed in range(1, 21):
            night = simulate_night(profile, 180.0, np.random.default_rng(seed))
            sets[name].append((night_to_grid(night), true_peak_times(night.schedule)))
    return sets


def detection_error_pct(trials: list[tuple[np.ndarray, np.ndarray]], **overrides: float) -> float:
    """Missed + fake breaths as a percent of the true breaths, pooled over the trials."""
    lo, hi = SENSITIVITY_WINDOW_S
    wrong = total = 0
    for L, true_s in trials:
        detected = analyse(L, **overrides).breaths.peak_idx / FS
        truth = true_s[(true_s >= lo) & (true_s <= hi)]
        missed, extra = detection_errors(detected[(detected >= lo) & (detected <= hi)], truth)
        wrong += missed + extra
        total += len(truth)
    return 100.0 * wrong / total


def belt_count(**overrides: float) -> int:
    trial = load_trial(REAL_BELT)
    a = analyse(trial.L_uH, trial.fs_hz, **overrides)
    window = (BELT_TRIM_S[0], trial.duration_s - BELT_TRIM_S[1])
    return count_complete_breaths(breaths_in_window(a.breaths, FS, *window), len(trial.L_uH))


def shallow_floor() -> str:
    """How shallow a breath can be before the detector starts missing it."""
    profile = replace(
        PROFILES["stable"],
        artifacts_per_hour=0,
        no_signal_per_hour=0,
        gaps_per_hour=0,
        pauses_per_hour=0,
        shallow_per_hour=40,
    )
    edges = [0.0, 0.35, 0.5, 0.7, 10.0]
    names = ["under 35%", "35-50%", "50-70%", "70% or more"]
    rows = []
    for prominence in (0.2, 0.15, 0.1, 0.05):
        seen = np.zeros(len(names), dtype=int)
        missed = np.zeros(len(names), dtype=int)
        for seed in range(1, 21):
            night = simulate_night(profile, 180.0, np.random.default_rng(seed))
            s = night.schedule
            detected = analyse(night_to_grid(night), prominence_fraction=prominence).breaths
            detected_s = detected.peak_idx / FS
            depth = s.amplitude_uh[s.is_breath] / BREATH_AMPLITUDE_UH
            for t, d in zip(true_peak_times(s), depth, strict=True):
                if not SENSITIVITY_WINDOW_S[0] <= t <= SENSITIVITY_WINDOW_S[1]:
                    continue
                k = int(np.searchsorted(edges, d, side="right")) - 1
                seen[k] += 1
                missed[k] += not np.any(np.abs(detected_s - t) <= 0.75)
        mark = " (used)" if prominence == DEFAULTS["prominence_fraction"] else ""
        rows.append(
            [f"{prominence}{mark}", *[f"{m} of {n}" for m, n in zip(missed, seen, strict=True)]]
        )
    return (
        "**How shallow can a breath be and still be found?** Breaths missed, grouped by depth"
        " relative to a normal breath (20 trials with shallow spells):\n\n"
        + table(["peak prominence", *names], rows)
        + "\n\n"
    )


def sensitivity(out: Path) -> str:
    sets = sensitivity_trials()
    text = (
        "## 5. What happens when each parameter is changed\n\n"
        "One parameter changes at a time; the rest stay at today's values (**bold** row)."
        " Error = missed breaths + fake breaths, as a percent of the true breaths, over 20"
        " synthetic 3-minute trials per set (truth known exactly; a missed and a fake breath"
        f" cannot cancel). Belt = complete breaths counted in the real belt file"
        f" ({BELT_VISIBLE_BREATHS} visible by eye).\n\n"
    )
    fig, axes = plt.subplots(1, len(SWEEPS), figsize=(17, 4.2), sharey=True)
    for ax, (param, values) in zip(axes, SWEEPS.items(), strict=True):
        rows = []
        curves = {name: [] for name in sets}
        for value in values:
            errs = [detection_error_pct(trials, **{param: value}) for trials in sets.values()]
            for name, e in zip(sets, errs, strict=True):
                curves[name].append(e)
            mark = "**" if value == DEFAULTS[param] else ""
            rows.append([f"{mark}{value}{mark}", *errs, belt_count(**{param: value})])
        text += (
            f"**{LABELS[param]}**\n\n"
            + table(["value", *[f"{n} (%)" for n in sets], "belt count"], rows)
            + "\n\n"
        )
        for name, ys in curves.items():
            ax.plot(range(len(values)), ys, "o-", ms=4, label=name)
        ax.set_xticks(range(len(values)), [str(v) for v in values])
        ax.axvline(values.index(DEFAULTS[param]), color="k", lw=0.6, ls=":")
        ax.axhline(5, color="tab:red", lw=0.6, ls="--")
        ax.set_xlabel(LABELS[param], fontsize=8)
    axes[0].set_ylabel("missed + fake breaths (%)")
    axes[0].set_ylim(0, 20)
    axes[0].legend(fontsize=7)
    fig.suptitle(
        "Detection error vs each parameter (dotted = value in use, dashed red = 5% target)"
    )
    name = save(fig, out, "5_sensitivity.png")
    return text + f"![]({name})\n\n" + shallow_floor()


# --- 6. Time resolution -------------------------------------------------------------------


def time_resolution(out: Path) -> str:
    """One recording with a 30 s burst, a slow rise and a pause, seen through four windows."""

    def rate(t: float) -> float:
        if 180 <= t < 210:
            return 28.0  # short burst of fast breathing
        if 420 <= t < 600:
            return 15.0 + 9.0 * (t - 420) / 180  # slow rise 15 -> 24 over 3 minutes
        if 600 <= t < 720:
            return 24.0
        return 15.0

    duration = 960.0
    rng = np.random.default_rng(11)
    schedule = build_schedule(duration, rate, pauses=((780.0, 15.0),), jitter=0.03, rng=rng)
    t, L = render(schedule, duration, rng)
    a = analyse(L)

    is_b = schedule.is_breath
    true_t = schedule.start_s[is_b] + schedule.duration_s[is_b] / 2
    true_rate = 60.0 / schedule.duration_s[is_b]
    centres = np.arange(0, duration, 5.0)
    windows = {"30 s window": 30.0, "1 min window (dashboard trend)": 60.0, "5 min window": 300.0}
    bb_t, bb = breath_by_breath(a.breaths, FS)

    fig, ax = plt.subplots(figsize=(13, 5))
    ax.step(true_t, true_rate, where="mid", color="k", lw=1.2, label="true (each breath)")
    ax.plot(bb_t, bb, ".", color="gray", ms=4, label="breath-by-breath (compare view)")
    curves = {}
    for (label, width), color in zip(
        windows.items(), ("tab:blue", "tab:orange", "tab:green"), strict=True
    ):
        curves[label] = windowed_rate(a.breaths, FS, centres, width)
        ax.plot(centres, curves[label], color=color, lw=1.8, label=label)
    ax.axvspan(780, 795, color="tab:red", alpha=0.12, label="15 s pause")
    ax.set_xlabel("seconds")
    ax.set_ylabel("breaths/min")
    ax.set_ylim(0, 34)
    ax.set_title("The same breathing through different rate windows")
    ax.legend(fontsize=8, ncol=3, loc="lower left")
    name = save(fig, out, "6_time_resolution.png")

    def seen(values: np.ndarray, times: np.ndarray, lo: float, hi: float, fn) -> float:
        m = (times >= lo) & (times <= hi) & np.isfinite(values)
        return float(fn(values[m])) if m.any() else float("nan")

    rows = [
        [
            "breath-by-breath",
            seen(bb, bb_t, 180, 210, np.max),
            seen(bb, bb_t, 775, 800, np.min),
        ]
    ]
    for label in windows:
        rows.append(
            [
                label,
                seen(curves[label], centres, 180, 210, np.max),
                seen(curves[label], centres, 775, 800, np.min),
            ]
        )
    return (
        f"## 6. Short changes vs long trends: the rate window\n\n![]({name})\n\n"
        "True values: steady 15 /min, a 30 s burst at 28 /min, a 15 s pause"
        " (a 15 s gap = 4 /min breath-by-breath).\n\n"
        + table(
            [
                "rate shown as",
                "highest rate seen in the burst (/min)",
                "lowest rate seen at the pause (/min)",
            ],
            rows,
        )
        + "\n"
    )


# --- 7. Events through the filter ---------------------------------------------------------


def pause_length_table() -> str:
    lengths = [6, 8, 11, 13, 15, 20, 30, 45]
    old_hits, new_hits = [], []
    for length in lengths:
        old = new = 0
        for seed in range(10):
            rng = np.random.default_rng(seed)
            start = 80.0 + 0.37 * seed
            s = build_schedule(
                180.0, lambda t: 16.0, pauses=((start, float(length)),), jitter=0.03, rng=rng
            )
            a = analyse(render(s, 180.0, rng)[1])
            old += len(pauses_old_rule(a.breaths)) == 1
            new += len(pauses_new_rule(a)) == 1
        old_hits.append(f"{old}/10")
        new_hits.append(f"{new}/10")
    return table(
        ["pause length (s)", *[str(v) for v in lengths]],
        [
            ["old rule (gaps in the filtered signal)", *old_hits],
            ["movement rule (used now)", *new_hits],
        ],
    )


def events(out: Path) -> str:
    rng = np.random.default_rng(3)
    duration = 180.0
    cases = {}

    s = build_schedule(duration, lambda t: 16.0, pauses=((80.0, 15.0),), jitter=0.03, rng=rng)
    cases["15 s breathing pause"] = (s, *render(s, duration, rng))

    s = build_schedule(duration, lambda t: 16.0, jitter=0.03, rng=rng)
    t, L = render(s, duration, rng)
    L = L + np.where(t >= 90.0, 5 * BREATH_AMPLITUDE_UH, 0.0)  # belt shifts and stays shifted
    cases["posture step (5 breath-depths) at 90 s"] = (s, t, L)

    s = build_schedule(
        duration, lambda t: 16.0, lambda t: 3.0 if 88 <= t < 91.5 else 1.0, jitter=0.03, rng=rng
    )
    cases["one sigh, 3x deeper"] = (s, *render(s, duration, rng))

    s = build_schedule(
        duration, lambda t: 16.0, lambda t: 1.0 + 0.6 * np.sin(2 * np.pi * t / 60), jitter=0.03,
        rng=rng,
    )  # fmt: skip
    cases["depth waxing and waning every 60 s"] = (s, *render(s, duration, rng))

    fig, axes = plt.subplots(len(cases), 1, figsize=(13, 10), sharex=True)
    rows = []
    for ax, (label, (schedule, t, L)) in zip(axes, cases.items(), strict=True):
        a = analyse(L)
        ax.plot(t, a.cleaned - np.nanmedian(a.cleaned), color="gray", lw=0.7, label="raw (centred)")
        ax.plot(t, a.filtered, color="tab:blue", lw=1.1, label="filtered")
        b = a.breaths
        ax.plot(b.peak_idx / FS, a.filtered[b.peak_idx], "v", color="tab:red", ms=4)
        ax.plot(b.trough_idx / FS, a.filtered[b.trough_idx], "^", color="tab:green", ms=4)
        ax.set_ylim(-0.12, 0.12)
        ax.set_title(label, fontsize=9)
        ax.set_ylabel("uH")
        truth = true_complete_breaths(schedule, 0.0, duration)
        got = count_complete_breaths(b, len(L))
        for p0, p1 in pauses_new_rule(a):
            ax.axvspan(p0, p1, color="tab:red", alpha=0.12)
        found = ", ".join(f"{p0:.1f}-{p1:.1f} s" for p0, p1 in pauses_new_rule(a)) or "none"
        old = ", ".join(f"{p0:.1f}-{p1:.1f} s" for p0, p1 in pauses_old_rule(b)) or "none"
        rows.append([label, truth, got, found, old])
    axes[0].legend(fontsize=8, loc="upper right")
    axes[-1].set_xlabel("seconds")
    name = save(fig, out, "7_events.png")

    # Depth tracking for the waxing/waning case: detected breath depth vs the true depth.
    schedule, t, L = cases["depth waxing and waning every 60 s"]
    a = analyse(L)
    p, tr = a.breaths.peak_idx, a.breaths.trough_idx
    before = np.searchsorted(tr, p) - 1
    ok = before >= 0
    depth = a.filtered[p[ok]] - a.filtered[tr[before[ok]]]
    true_peak_s = schedule.start_s + INHALE_FRACTION * schedule.duration_s
    nearest = np.abs(true_peak_s[None, :] - (p[ok] / FS)[:, None]).argmin(axis=1)
    edge = (p[ok] / FS > 15) & (p[ok] / FS < duration - 15)
    r = np.corrcoef(depth[edge], schedule.amplitude_uh[nearest][edge])[0, 1]
    ratio = np.median(depth[edge] / schedule.amplitude_uh[nearest][edge])
    return (
        f"## 7. Clinically interesting events, before and after the filter\n\n![]({name})\n\n"
        + table(
            [
                "event",
                "true complete breaths",
                "counted",
                "pauses > 10 s reported (movement rule, used now)",
                "old rule (gaps in the filtered signal)",
            ],
            rows,
        )
        + "\n\nThe true pause in the first row starts at about 80 s and lasts 15 s. Pauses found"
        " out of 10 recordings each (16 breaths/min, pause length varied):\n\n"
        + pause_length_table()
        + f"\n\n- Waxing/waning depth: detected breath depth follows the true depth with"
        f" correlation r = {r:.3f}; median detected/true depth = {ratio:.2f}.\n"
    )


# --- 8. Phase -----------------------------------------------------------------------------


def phase(out: Path) -> str:
    """Peak timing with the forward-backward filter vs an ordinary one-pass filter."""
    sos = butter(2, [0.1, 1.0], btype="bandpass", fs=FS, output="sos")

    def shift_ms(peak_idx: np.ndarray, true_peaks: np.ndarray) -> int:
        at = peak_idx / FS
        at = at[(at > 30) & (at < 150)]
        nearest = true_peaks[np.abs(true_peaks[None, :] - at[:, None]).argmin(axis=1)]
        return round(float(np.median(at - nearest) * 1000))

    rows = []
    for rate in (8, 12, 16, 24, 32):
        rng = np.random.default_rng(rate)
        schedule = build_schedule(180.0, lambda t, r=rate: float(r))
        t, L = render(schedule, 180.0, rng)
        a = analyse(L)
        one_pass = sosfilt(sos, a.cleaned - np.median(a.cleaned))
        true_peaks = true_peak_times(schedule)
        rows.append(
            [
                rate,
                shift_ms(a.breaths.peak_idx, true_peaks),
                shift_ms(detect_breaths(one_pass, FS).peak_idx, true_peaks),
            ]
        )

    # The plot shows the last (fastest) case, where the one-pass delay is easiest to see.
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(t, a.cleaned - np.median(a.cleaned) - 0.03, color="gray", lw=0.8, label="raw (centred)")
    ax.plot(t, a.filtered, color="tab:blue", lw=1.4, label="forward + backward (used)")
    ax.plot(t, one_pass, color="tab:red", lw=1.0, ls="--", label="ordinary one-pass filter")
    for tp in true_peaks:
        ax.axvline(tp, color="k", lw=0.4, alpha=0.5)
    ax.set_xlim(60, 75)
    ax.set_xlabel("seconds (vertical lines = true inhale peaks), breathing at 32 /min")
    ax.set_ylabel("uH")
    ax.legend(fontsize=8, loc="upper right")
    ax.set_title("Running the filter forward and backward keeps breath peaks at their true times")
    name = save(fig, out, "8_phase.png")
    return (
        f"## 8. Why the filter runs forward and backward\n\n![]({name})\n\n"
        "How far the detected inhale peak sits from the true one (median, ms; one sample ="
        " 40 ms; + means late):\n\n"
        + table(["breaths/min", "forward + backward (used)", "one pass"], rows)
        + "\n"
    )


# --- Main ---------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure what each filter parameter does.")
    parser.add_argument("--out", type=Path, default=REPO / "docs" / "figures" / "filtering")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)

    parts = [
        "# Filter study results\n\nGenerated by `tools/filter_study.py`. Do not edit by hand.\n"
    ]
    parts.append(frequency_response(args.out))
    if REAL_BELT.exists():
        parts.append(what_is_removed(args.out))
        parts.append(rejected_readings())
    else:
        print(f"Skipping the real-recording sections: {REAL_BELT} not found")
    parts.append(rate_range(args.out))
    parts.append(sensitivity(args.out) if REAL_BELT.exists() else "")
    parts.append(time_resolution(args.out))
    parts.append(events(args.out))
    parts.append(phase(args.out))
    results = args.out / "RESULTS.md"
    results.write_text("\n".join(p for p in parts if p), encoding="utf-8")
    print(f"Wrote {results} and the figures next to it")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
