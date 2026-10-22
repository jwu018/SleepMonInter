"use client";

import { useEffect, useMemo, useState } from "react";
import type uPlot from "uplot";
import type { WaveformWindow } from "@/lib/data/types";
import { axisStyle, type ChartTheme, UPlotChart } from "./UPlotChart";

// The raw breathing signal for a chosen time window.
// Each zoom change asks the server for just that window, already reduced to ~1600 points,
// so the browser never downloads the whole night at full resolution.

const ZOOMS = [
  { label: "Full night", span_ms: Infinity },
  { label: "1 h", span_ms: 60 * 60_000 },
  { label: "5 min", span_ms: 5 * 60_000 },
  { label: "30 s", span_ms: 30_000 },
] as const;
const MAX_POINTS = 3200; // enough to show a 5-minute window (3,000 points at 10 Hz) unreduced

interface Props {
  recordingId: string;
  startUtc: string;
  durationMs: number;
  /** When set (e.g. by clicking a trend chart), jump to a 5-minute window centered here. */
  focusMs?: number | null;
}

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; window: WaveformWindow };

export function WaveformPanel({ recordingId, startUtc, durationMs, focusMs }: Props) {
  const [spanMs, setSpanMs] = useState(durationMs);
  const [startMs, setStartMs] = useState(0);
  const [state, setState] = useState<LoadState>({ status: "loading" });

  // React to a new focus point from the trend charts.
  const [lastFocus, setLastFocus] = useState<number | null>(null);
  if (focusMs != null && focusMs !== lastFocus) {
    // Adjusting state during render (instead of in an effect) is React's recommended way to
    // respond to a prop change: https://react.dev/learn/you-might-not-need-an-effect
    setLastFocus(focusMs);
    const span = 5 * 60_000;
    setSpanMs(span);
    setStartMs(clamp(focusMs - span / 2, 0, Math.max(0, durationMs - span)));
  }

  const endMs = Math.min(durationMs, startMs + spanMs);

  useEffect(() => {
    // AbortController cancels the previous request if the user clicks again quickly,
    // so an old, slower response can't overwrite a newer one.
    const controller = new AbortController();
    const url = `/api/recordings/${encodeURIComponent(recordingId)}/waveform?start_ms=${Math.floor(startMs)}&end_ms=${Math.ceil(endMs)}&max_points=${MAX_POINTS}`;
    fetch(url, { signal: controller.signal })
      .then(async (res) => {
        if (!res.ok) throw new Error(`Server returned ${res.status}`);
        setState({ status: "ready", window: (await res.json()) as WaveformWindow });
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setState({ status: "error", message: err instanceof Error ? err.message : String(err) });
      });
    return () => controller.abort();
  }, [recordingId, startMs, endMs]);

  const startS = Date.parse(startUtc) / 1000;
  const data: uPlot.AlignedData = useMemo(() => {
    if (state.status !== "ready") return [[], []];
    return [state.window.t_ms.map((t) => startS + t / 1000), state.window.raw_value];
  }, [state, startS]);

  function zoomTo(span: number) {
    const newSpan = Math.min(span, durationMs);
    // Keep the middle of the current view in the middle of the new one.
    const center = startMs + spanMs / 2;
    setSpanMs(newSpan);
    setStartMs(clamp(center - newSpan / 2, 0, Math.max(0, durationMs - newSpan)));
  }

  function pan(direction: -1 | 1) {
    setStartMs((s) => clamp(s + direction * spanMs * 0.8, 0, Math.max(0, durationMs - spanMs)));
  }

  const makeOptions = (theme: ChartTheme, width: number): uPlot.Options => ({
    width,
    height: 220,
    cursor: { drag: { x: false, y: false }, points: { show: false } },
    scales: { x: { time: true } },
    series: [
      {},
      {
        label: "Raw signal",
        stroke: theme.series[0],
        width: 1,
        points: { show: false },
        value: (_u, v, _s, idx) => (idx == null ? "—" : v == null ? "gap" : `${Math.round(v)} counts`),
      },
    ],
    axes: [axisStyle(theme), axisStyle(theme, { size: 64 })],
  });

  const atStart = startMs <= 0;
  const atEnd = endMs >= durationMs;
  const fullNight = spanMs >= durationMs;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <div role="group" aria-label="Zoom" className="flex overflow-hidden rounded-md border border-border">
          {ZOOMS.map((z) => {
            const active = Math.min(z.span_ms, durationMs) === spanMs;
            return (
              <button
                key={z.label}
                type="button"
                onClick={() => zoomTo(z.span_ms)}
                aria-pressed={active}
                className={`px-3 py-1.5 text-sm ${active ? "bg-accent text-background" : "hover:bg-surface"}`}
              >
                {z.label}
              </button>
            );
          })}
        </div>
        <div className="flex gap-1">
          <button
            type="button"
            onClick={() => pan(-1)}
            disabled={atStart || fullNight}
            className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-surface disabled:opacity-40"
          >
            ← Earlier
          </button>
          <button
            type="button"
            onClick={() => pan(1)}
            disabled={atEnd || fullNight}
            className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-surface disabled:opacity-40"
          >
            Later →
          </button>
        </div>
        <span className="text-xs text-muted">
          {state.status === "ready" && state.window.resolution === "envelope"
            ? "Zoomed out: showing the min–max envelope of the signal"
            : "Showing every point (10 Hz)"}
        </span>
      </div>

      {!fullNight && (
        <input
          type="range"
          aria-label="Position in the night"
          min={0}
          max={Math.max(0, durationMs - spanMs)}
          step={Math.max(1000, spanMs / 20)}
          value={startMs}
          onChange={(e) => setStartMs(Number(e.target.value))}
          className="w-full accent-[var(--accent)]"
        />
      )}

      <div className="relative">
        <UPlotChart data={data} height={220} makeOptions={makeOptions} />
        {state.status === "loading" && (
          <p className="absolute inset-0 grid place-items-center text-sm text-muted">Loading signal…</p>
        )}
        {state.status === "error" && (
          <p className="absolute inset-0 grid place-items-center text-sm text-muted">
            Couldn&apos;t load the signal ({state.message}).
          </p>
        )}
      </div>
      <p className="text-xs text-muted">
        Units are raw sensor counts: only changes are meaningful, not the absolute level.
        Tip: click a point on the trend charts above to jump here.
      </p>
    </div>
  );
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}
