"use client";

import { useMemo, useState } from "react";
import type uPlot from "uplot";
import { axisStyle, type ChartTheme, UPlotChart } from "@/components/charts/UPlotChart";
import type { DeviceRecording } from "@/lib/device/parseDeviceCsv";
import { deviceClockTime, formatElapsed, tracePoints } from "@/lib/device/trace";

// The raw signal of an uploaded recording, with zoom presets like the night view's
// waveform panel. Everything is computed in the browser from the parsed file.

type Channel = "ldc_L_uH" | "ldc_freq_hz" | "a0_raw";
const CHANNELS: Record<Channel, { label: string; unit: string; digits: number }> = {
  ldc_L_uH: { label: "Belt inductance", unit: "µH", digits: 5 },
  ldc_freq_hz: { label: "Sensor frequency", unit: "Hz", digits: 1 },
  a0_raw: { label: "Auxiliary input a0 (debug only)", unit: "counts", digits: 0 },
};
const ZOOMS = [
  { label: "Whole recording", span_ms: Infinity },
  { label: "5 min", span_ms: 5 * 60_000 },
  { label: "30 s", span_ms: 30_000 },
  { label: "5 s", span_ms: 5_000 },
] as const;
const MAX_POINTS = 3000;

export function DeviceTrace({ recording }: { recording: DeviceRecording }) {
  const { columns, stats, meta } = recording;
  const hasSensor = stats.sensor_rows > 0;
  const totalMs = columns.elapsed_ms.length ? columns.elapsed_ms[columns.elapsed_ms.length - 1] + 1 : 0;

  const [channel, setChannel] = useState<Channel>(hasSensor ? "ldc_L_uH" : "a0_raw");
  const [timeMode, setTimeMode] = useState<"elapsed" | "clock">("elapsed");
  const [spanMs, setSpanMs] = useState(totalMs);
  const [startMs, setStartMs] = useState(0);
  const endMs = Math.min(totalMs, startMs + spanMs);

  const points = useMemo(
    () => tracePoints(columns.elapsed_ms, columns[channel], startMs, endMs, MAX_POINTS),
    [columns, channel, startMs, endMs],
  );
  const data: uPlot.AlignedData = useMemo(() => [points.x, points.y], [points]);

  const formatX = (seconds: number) =>
    timeMode === "clock" ? (deviceClockTime(meta.start_local, seconds) ?? formatElapsed(seconds)) : formatElapsed(seconds);

  const info = CHANNELS[channel];
  const makeOptions = (theme: ChartTheme, width: number): uPlot.Options => ({
    width,
    height: 260,
    cursor: { drag: { x: false, y: false }, points: { show: false } },
    scales: { x: { time: false } },
    series: [
      { label: timeMode === "clock" ? "Device clock" : "Elapsed", value: (_u, v) => (v == null ? "—" : formatX(v)) },
      {
        label: info.label,
        stroke: channel === "a0_raw" ? theme.neutral : theme.series[0],
        width: 1,
        points: { show: false },
        value: (_u, v, _s, idx) =>
          idx == null ? "—" : v == null ? "no value" : `${v.toFixed(info.digits)} ${info.unit}`,
      },
    ],
    axes: [
      axisStyle(theme, { values: (_u, ticks) => ticks.map(formatX) }),
      axisStyle(theme, { size: 80, label: info.unit }),
    ],
  });

  function zoomTo(span: number) {
    const newSpan = Math.min(span, totalMs);
    const center = startMs + spanMs / 2;
    setSpanMs(newSpan);
    setStartMs(clamp(center - newSpan / 2, 0, Math.max(0, totalMs - newSpan)));
  }
  const pan = (dir: -1 | 1) =>
    setStartMs((s) => clamp(s + dir * spanMs * 0.8, 0, Math.max(0, totalMs - spanMs)));
  const whole = spanMs >= totalMs;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
        <label className="flex items-center gap-2">
          <span className="text-muted">Signal</span>
          <select
            value={channel}
            onChange={(e) => setChannel(e.target.value as Channel)}
            className="rounded-md border border-border bg-background px-2 py-1"
          >
            {(Object.keys(CHANNELS) as Channel[]).map((c) => (
              <option key={c} value={c} disabled={c !== "a0_raw" && !hasSensor}>
                {CHANNELS[c].label}
                {c !== "a0_raw" && !hasSensor ? " (no sensor data)" : ""}
              </option>
            ))}
          </select>
        </label>
        <fieldset className="flex items-center gap-3">
          <legend className="sr-only">Time axis</legend>
          <span className="text-muted">Time axis</span>
          <label className="flex items-center gap-1">
            <input type="radio" checked={timeMode === "elapsed"} onChange={() => setTimeMode("elapsed")} />
            Time since start
          </label>
          <label className="flex items-center gap-1">
            <input type="radio" checked={timeMode === "clock"} onChange={() => setTimeMode("clock")} />
            Device clock
          </label>
        </fieldset>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div role="group" aria-label="Zoom" className="flex overflow-hidden rounded-md border border-border">
          {ZOOMS.map((z) => {
            const active = Math.min(z.span_ms, totalMs) === spanMs;
            return (
              <button
                key={z.label}
                type="button"
                onClick={() => zoomTo(z.span_ms)}
                disabled={z.span_ms !== Infinity && z.span_ms >= totalMs}
                aria-pressed={active}
                className={`px-3 py-1.5 text-sm disabled:opacity-40 ${active ? "bg-accent text-background" : "hover:bg-surface"}`}
              >
                {z.label}
              </button>
            );
          })}
        </div>
        <button
          type="button"
          onClick={() => pan(-1)}
          disabled={whole || startMs <= 0}
          className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-surface disabled:opacity-40"
        >
          ← Earlier
        </button>
        <button
          type="button"
          onClick={() => pan(1)}
          disabled={whole || endMs >= totalMs}
          className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-surface disabled:opacity-40"
        >
          Later →
        </button>
        <span className="text-xs text-muted">
          {points.resolution === "envelope" ? "Zoomed out: showing the min–max envelope" : "Showing every sample (25 Hz)"}
        </span>
      </div>

      {!hasSensor && (
        <p className="rounded-md border border-status-neutral/60 bg-status-neutral/10 px-3 py-2 text-sm">
          The inductance sensor wasn&apos;t connected for this recording, so there&apos;s no breathing
          signal. Showing the auxiliary input instead, which is for debugging only.
        </p>
      )}

      {/* Rebuild when the axis formatting or series label changes. */}
      <UPlotChart data={data} height={260} makeOptions={makeOptions} deps={[channel, timeMode]} />
      <p className="text-xs text-muted">
        Device clock is the logger&apos;s own clock (no time zone). If it was set wrong, use
        &quot;Time since start&quot;, which is always reliable.
      </p>
    </div>
  );
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}
