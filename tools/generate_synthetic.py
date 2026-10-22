"""Generate a synthetic Night Night overnight recording.

The output follows docs/FILE_FORMAT.md exactly, so the rest of the system can't tell
a synthetic file from a real one (apart from the extra `synthetic=true` header key).

How the signal is built (all in "counts", the raw unit of the RIP front end):

    raw_value = offset + breathing + baseline wander + sensor noise + artifacts

1. A breath schedule is built one breath at a time. Each breath's length comes from a
   slowly drifting target respiratory rate plus random breath-to-breath jitter, and
   pauses (apneas) are inserted between breaths.
2. Each breath gets an amplitude (depth): slow variation, an overnight trend, and
   occasional stretches of shallow breathing.
3. The schedule is turned into a waveform at 20 Hz using a smooth rise (inhale) and
   fall (exhale) per breath.
4. Wander, noise, motion artifacts and "band loose" (no-signal) stretches are added,
   then a few data gaps are cut out of the timestamps.

Usage:
    python generate_synthetic.py --profile stable --seed 1 --out night.csv
    python generate_synthetic.py --help
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

# --- Fixed by the file format / device -------------------------------------------------
FORMAT_VERSION = 1
FIRMWARE_VERSION = "0.1.0"
SAMPLE_PERIOD_MS = 50  # 20 Hz
BATTERY_LOG_PERIOD_MS = 60_000  # battery_mv is written once per minute

# --- Signal model constants -------------------------------------------------------------
RAW_OFFSET_COUNTS = 50_000  # resting value of the front end; only changes matter
BREATH_AMPLITUDE_COUNTS = 300.0  # peak-to-trough of a typical breath at the start of the night
INHALE_FRACTION = 0.4  # inhaling takes ~40% of a breath cycle, exhaling ~60%
MAX_RR_BPM = 30.0
MIN_RR_BPM = 8.0


@dataclass(frozen=True)
class Profile:
    """Knobs that define a type of night. All `*_per_hour` values are average event rates."""

    rr_start_bpm: tuple[float, float]  # baseline RR at lights-off is drawn from this range
    rr_trend_bpm: float  # change in baseline RR from start to end of the night
    rr_wander_bpm: float  # size of slow drift around the trend
    breath_jitter: float  # std dev of breath-to-breath period variation (fraction of period)
    amplitude_end: float  # baseline amplitude at the end of the night, relative to the start
    shallow_per_hour: float
    pauses_per_hour: float
    artifacts_per_hour: float
    no_signal_per_hour: float
    gaps_per_hour: float
    noise_rel: float  # sensor noise std dev, as a fraction of breath amplitude
    wander_rel: float  # baseline wander size, as a fraction of breath amplitude


PROFILES: dict[str, Profile] = {
    # A well-controlled night: steady rate, few events.
    "stable": Profile(
        rr_start_bpm=(16.0, 20.0),
        rr_trend_bpm=0.5,
        rr_wander_bpm=1.0,
        breath_jitter=0.07,
        amplitude_end=0.95,
        shallow_per_hour=0.5,
        pauses_per_hour=1.0,
        artifacts_per_hour=2.0,
        no_signal_per_hour=0.05,
        gaps_per_hour=0.1,
        noise_rel=0.03,
        wander_rel=0.4,
    ),
    # Worsening respiratory muscle weakness: faster, shallower breathing as the night goes on.
    "declining": Profile(
        rr_start_bpm=(17.0, 21.0),
        rr_trend_bpm=4.0,
        rr_wander_bpm=1.0,
        breath_jitter=0.09,
        amplitude_end=0.65,
        shallow_per_hour=2.0,
        pauses_per_hour=3.0,
        artifacts_per_hour=2.0,
        no_signal_per_hour=0.05,
        gaps_per_hour=0.1,
        noise_rel=0.03,
        wander_rel=0.4,
    ),
    # A restless night with a loosely fitted band: lots of motion and noise.
    "noisy": Profile(
        rr_start_bpm=(16.0, 22.0),
        rr_trend_bpm=0.5,
        rr_wander_bpm=1.5,
        breath_jitter=0.08,
        amplitude_end=0.95,
        shallow_per_hour=0.5,
        pauses_per_hour=1.0,
        artifacts_per_hour=10.0,
        no_signal_per_hour=0.3,
        gaps_per_hour=0.3,
        noise_rel=0.10,
        wander_rel=1.0,
    ),
}


@dataclass(frozen=True)
class Event:
    """Something the generator put into the signal on purpose, for later ground truth."""

    kind: str  # pause, shallow, artifact_spike, artifact_burst, baseline_shift, no_signal, data_gap
    start_ms: int
    end_ms: int


@dataclass
class BreathSchedule:
    """Back-to-back segments covering the night. A segment is either one breath or a pause."""

    start_s: np.ndarray
    duration_s: np.ndarray
    amplitude_counts: np.ndarray  # 0 for pauses
    is_breath: np.ndarray  # bool


@dataclass
class SyntheticNight:
    """Everything the generator produced, before it's written to disk."""

    timestamp_ms: np.ndarray  # int64, after data gaps are removed
    raw_value: np.ndarray  # int64, same length as timestamp_ms
    battery_mv: np.ndarray  # float64, NaN on rows where the battery isn't logged
    schedule: BreathSchedule
    events: list[Event] = field(default_factory=list)


# --- Small building blocks --------------------------------------------------------------


def slow_wave(
    rng: np.random.Generator, t_s: np.ndarray, period_range_s: tuple[float, float]
) -> np.ndarray:
    """A smooth random curve scaled to roughly [-1, 1].

    It's the sum of a few sine waves with random periods and phases. This is a cheap way to
    get "slow drift" that looks natural rather than periodic.
    """
    wave = np.zeros_like(t_s, dtype=float)
    for _ in range(3):
        period_s = rng.uniform(*period_range_s)
        phase = rng.uniform(0, 2 * np.pi)
        wave += rng.uniform(0.5, 1.0) * np.sin(2 * np.pi * t_s / period_s + phase)
    peak = np.max(np.abs(wave))
    return wave / peak if peak > 0 else wave


def random_intervals(
    rng: np.random.Generator,
    rate_per_hour: float,
    duration_s: float,
    length_range_s: tuple[float, float],
) -> list[tuple[float, float]]:
    """Random (start_s, length_s) intervals, sorted by start.

    The count is Poisson-distributed: on average `rate_per_hour` events per hour, but
    some nights get more and some get none, like real events.
    """
    count = rng.poisson(rate_per_hour * duration_s / 3600)
    starts = np.sort(rng.uniform(0, duration_s, size=count))
    return [(float(s), float(rng.uniform(*length_range_s))) for s in starts]


def breath_shape(phase: np.ndarray) -> np.ndarray:
    """Chest expansion over one breath, for phase in [0, 1). Returns values in [0, 1].

    Half-cosine up during inhalation, then half-cosine down during the longer exhalation.
    Both halves meet smoothly at 0 and 1, so consecutive breaths join without jumps.
    """
    inhaling = phase < INHALE_FRACTION
    rise = 0.5 * (1 - np.cos(np.pi * phase / INHALE_FRACTION))
    fall = 0.5 * (1 + np.cos(np.pi * (phase - INHALE_FRACTION) / (1 - INHALE_FRACTION)))
    return np.where(inhaling, rise, fall)


# --- Main simulation steps --------------------------------------------------------------


def build_breath_schedule(
    profile: Profile, duration_s: float, rng: np.random.Generator, events: list[Event]
) -> BreathSchedule:
    """Lay out breaths and pauses back to back until the night is covered."""
    # Precompute slow curves on a 1 s grid, then look them up by whole second in the loop.
    grid_s = np.arange(0, int(duration_s) + 2, dtype=float)
    progress = grid_s / duration_s  # 0 at lights-off, 1 at the end of the night
    rr_start = rng.uniform(*profile.rr_start_bpm)
    rr_target = (
        rr_start
        + profile.rr_trend_bpm * progress
        + profile.rr_wander_bpm * slow_wave(rng, grid_s, (20 * 60, 90 * 60))
    )
    amp_target = (
        BREATH_AMPLITUDE_COUNTS
        * (1 + (profile.amplitude_end - 1) * progress)
        * (1 + 0.1 * slow_wave(rng, grid_s, (10 * 60, 40 * 60)))
    )

    shallow = random_intervals(rng, profile.shallow_per_hour, duration_s, (60, 300))
    shallow_factors = [rng.uniform(0.3, 0.6) for _ in shallow]
    for start_s, length_s in shallow:
        events.append(Event("shallow", round(start_s * 1000), round((start_s + length_s) * 1000)))

    pauses = random_intervals(rng, profile.pauses_per_hour, duration_s, (5, 20))
    next_pause = 0

    starts: list[float] = []
    durations: list[float] = []
    amplitudes: list[float] = []
    is_breath: list[bool] = []

    t = 0.0
    while t < duration_s:
        # Pauses start at the end of a breath (end of exhalation), as real apneas do.
        if next_pause < len(pauses) and t >= pauses[next_pause][0]:
            length_s = pauses[next_pause][1]
            starts.append(t)
            durations.append(length_s)
            amplitudes.append(0.0)
            is_breath.append(False)
            events.append(Event("pause", round(t * 1000), round((t + length_s) * 1000)))
            t += length_s
            next_pause += 1
            continue

        second = int(t)
        rr_bpm = float(np.clip(rr_target[second], MIN_RR_BPM, MAX_RR_BPM))
        period_s = (60.0 / rr_bpm) * (1 + profile.breath_jitter * rng.standard_normal())
        period_s = max(period_s, 60.0 / MAX_RR_BPM)

        amplitude = amp_target[second] * (1 + 0.05 * rng.standard_normal())
        for (start_s, length_s), factor in zip(shallow, shallow_factors, strict=True):
            if start_s <= t < start_s + length_s:
                amplitude *= factor

        starts.append(t)
        durations.append(period_s)
        amplitudes.append(amplitude)
        is_breath.append(True)
        t += period_s

    return BreathSchedule(
        start_s=np.array(starts),
        duration_s=np.array(durations),
        amplitude_counts=np.array(amplitudes),
        is_breath=np.array(is_breath),
    )


def render_breathing(schedule: BreathSchedule, t_s: np.ndarray) -> np.ndarray:
    """Turn the breath schedule into a waveform sampled at times `t_s`."""
    # For each sample, find which segment it falls in (the last segment starting at or before it).
    segment = np.searchsorted(schedule.start_s, t_s, side="right") - 1
    phase = (t_s - schedule.start_s[segment]) / schedule.duration_s[segment]
    phase = np.clip(phase, 0.0, 1.0)
    shape = np.where(schedule.is_breath[segment], breath_shape(phase), 0.0)
    return shape * schedule.amplitude_counts[segment]


def add_no_signal(
    breathing: np.ndarray,
    profile: Profile,
    duration_s: float,
    rng: np.random.Generator,
    events: list[Event],
) -> None:
    """Simulate the band slipping loose: breathing almost disappears for a few minutes."""
    for start_s, length_s in random_intervals(
        rng, profile.no_signal_per_hour, duration_s, (120, 600)
    ):
        i0 = int(start_s * 1000 / SAMPLE_PERIOD_MS)
        i1 = int((start_s + length_s) * 1000 / SAMPLE_PERIOD_MS)
        breathing[i0:i1] *= 0.03
        events.append(Event("no_signal", round(start_s * 1000), round((start_s + length_s) * 1000)))


def add_artifacts(
    signal: np.ndarray,
    profile: Profile,
    duration_s: float,
    rng: np.random.Generator,
    events: list[Event],
) -> None:
    """Add motion artifacts in place: spikes, bursts of movement, and baseline shifts."""
    n = len(signal)
    for start_s, _ in random_intervals(rng, profile.artifacts_per_hour, duration_s, (0, 0)):
        i0 = int(start_s * 1000 / SAMPLE_PERIOD_MS)
        start_ms = i0 * SAMPLE_PERIOD_MS
        kind = rng.choice(["artifact_spike", "artifact_burst", "baseline_shift"], p=[0.4, 0.4, 0.2])

        if kind == "artifact_spike":
            # A jolt lasting 1-3 samples, e.g. bumping the electronics.
            width = int(rng.integers(1, 4))
            signal[i0 : i0 + width] += (
                rng.choice([-1, 1]) * rng.uniform(3, 8) * BREATH_AMPLITUDE_COUNTS
            )
            end_ms = start_ms + width * SAMPLE_PERIOD_MS
        elif kind == "artifact_burst":
            # Rolling over: several seconds of large, fairly slow random movement.
            width = int(rng.uniform(2, 10) * 1000 / SAMPLE_PERIOD_MS)
            width = min(width, n - i0)
            movement = rng.normal(0, rng.uniform(1, 3) * BREATH_AMPLITUDE_COUNTS, width)
            # A short moving average makes the movement smoother than white noise.
            movement = np.convolve(movement, np.ones(5) / 5, mode="same")
            signal[i0 : i0 + width] += movement
            end_ms = start_ms + width * SAMPLE_PERIOD_MS
        else:
            # The band shifts position and settles at a new resting level for the rest of the night.
            signal[i0:] += rng.uniform(-3, 3) * BREATH_AMPLITUDE_COUNTS
            end_ms = start_ms + SAMPLE_PERIOD_MS

        events.append(Event(str(kind), start_ms, end_ms))


def battery_curve(t_s: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Battery voltage in mV. Falls slowly at first, then faster as the cell empties."""
    hours = t_s / 3600
    start_mv = rng.uniform(4100, 4180)
    return start_mv - 45 * hours - 3 * hours**2 + rng.normal(0, 2, size=len(t_s))


def make_gap_mask(
    n_samples: int,
    profile: Profile,
    duration_s: float,
    rng: np.random.Generator,
    events: list[Event],
) -> np.ndarray:
    """Boolean mask of samples to keep. False = lost (e.g. the SD card write stalled)."""
    keep = np.ones(n_samples, dtype=bool)
    for start_s, length_s in random_intervals(rng, profile.gaps_per_hour, duration_s, (2, 30)):
        start_s = max(start_s, 60.0)  # keep the first minute intact
        i0 = int(start_s * 1000 / SAMPLE_PERIOD_MS)
        i1 = min(int((start_s + length_s) * 1000 / SAMPLE_PERIOD_MS), n_samples)
        if i1 <= i0:
            continue
        keep[i0:i1] = False
        events.append(Event("data_gap", i0 * SAMPLE_PERIOD_MS, i1 * SAMPLE_PERIOD_MS))
    return keep


def simulate_night(profile: Profile, duration_s: float, rng: np.random.Generator) -> SyntheticNight:
    """Run the whole simulation and return the samples plus the events that were injected."""
    events: list[Event] = []
    n_samples = int(duration_s * 1000 / SAMPLE_PERIOD_MS)
    timestamp_ms = np.arange(n_samples, dtype=np.int64) * SAMPLE_PERIOD_MS
    t_s = timestamp_ms / 1000

    schedule = build_breath_schedule(profile, duration_s, rng, events)
    breathing = render_breathing(schedule, t_s)
    add_no_signal(breathing, profile, duration_s, rng, events)

    wander = profile.wander_rel * BREATH_AMPLITUDE_COUNTS * slow_wave(rng, t_s, (5 * 60, 30 * 60))
    noise = rng.normal(0, profile.noise_rel * BREATH_AMPLITUDE_COUNTS, n_samples)
    signal = breathing + wander + noise
    add_artifacts(signal, profile, duration_s, rng, events)

    # Quantize to unsigned integer counts, as the hardware would.
    raw_value = np.clip(np.rint(RAW_OFFSET_COUNTS + signal), 0, None).astype(np.int64)

    battery_mv = battery_curve(t_s, rng)
    battery_mv[timestamp_ms % BATTERY_LOG_PERIOD_MS != 0] = np.nan

    keep = make_gap_mask(n_samples, profile, duration_s, rng, events)
    events.sort(key=lambda e: e.start_ms)

    return SyntheticNight(
        timestamp_ms=timestamp_ms[keep],
        raw_value=raw_value[keep],
        battery_mv=battery_mv[keep],
        schedule=schedule,
        events=events,
    )


# --- Output ------------------------------------------------------------------------------


def format_utc(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_recording(
    night: SyntheticNight,
    path: Path,
    *,
    device_id: str,
    start_utc: datetime,
    extra_header: dict[str, str],
) -> None:
    """Write `night` to `path` in the Night Night recording format."""
    header = {
        "night_night_format": str(FORMAT_VERSION),
        "device_id": device_id,
        "firmware": FIRMWARE_VERSION,
        "start_utc": format_utc(start_utc),
        "sample_period_ms": str(SAMPLE_PERIOD_MS),
        **extra_header,
    }
    lines = [f"# {key}={value}" for key, value in header.items()]
    lines.append("timestamp_ms,raw_value,battery_mv")

    battery = ["" if np.isnan(mv) else str(round(mv)) for mv in night.battery_mv.tolist()]
    lines.extend(
        f"{ts},{raw},{mv}"
        for ts, raw, mv in zip(
            night.timestamp_ms.tolist(), night.raw_value.tolist(), battery, strict=True
        )
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    # newline="\n" keeps Unix line endings on Windows too, matching what the firmware writes.
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


def parse_utc(text: str) -> datetime:
    """Parse an ISO 8601 time such as 2026-11-03T03:12:00Z into an aware UTC datetime."""
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        raise argparse.ArgumentTypeError("start time must include a timezone, e.g. a trailing Z")
    return dt.astimezone(UTC)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a synthetic Night Night recording (docs/FILE_FORMAT.md)."
    )
    parser.add_argument("--profile", choices=sorted(PROFILES), default="stable")
    parser.add_argument("--seed", type=int, default=0, help="same seed -> identical file")
    parser.add_argument("--duration-hours", type=float, default=8.0)
    parser.add_argument(
        "--start-utc",
        type=parse_utc,
        default=parse_utc("2026-10-01T02:30:00Z"),
        help="recording start in UTC (default: 2026-10-01T02:30:00Z, i.e. 10:30 pm US Eastern)",
    )
    parser.add_argument("--device-id", default="NN-DEV-01")
    parser.add_argument("--out", type=Path, required=True, help="output .csv path")
    args = parser.parse_args(argv)

    if args.duration_hours <= 0:
        parser.error("--duration-hours must be positive")

    rng = np.random.default_rng(args.seed)
    night = simulate_night(PROFILES[args.profile], args.duration_hours * 3600, rng)
    write_recording(
        night,
        args.out,
        device_id=args.device_id,
        start_utc=args.start_utc,
        extra_header={"synthetic": "true", "profile": args.profile, "seed": str(args.seed)},
    )

    counts: dict[str, int] = {}
    for event in night.events:
        counts[event.kind] = counts.get(event.kind, 0) + 1
    summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "none"
    print(f"Wrote {args.out} ({len(night.timestamp_ms):,} samples). Events: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
