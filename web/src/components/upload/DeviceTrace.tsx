"use client";

import { useMemo, useState } from "react";
import type uPlot from "uplot";
import { breathMarkersPlugin } from "@/components/charts/breathMarkers";
import { markerPlugin } from "@/components/charts/markerPlugin";
import { pickHooks, QualityLegend, qualityShading } from "@/components/charts/NightTrends";
import { axisStyle, type ChartTheme, UPlotChart } from "@/components/charts/UPlotChart";
import type { DeviceRecording } from "@/lib/device/parseDeviceCsv";
import { deviceClockTime, formatElapsed, tracePoints } from "@/lib/device/trace";
import type { BreathingAnalysis } from "@/lib/processing/breathing";

// The raw signal of an uploaded recording, with zoom presets like the night view's
// waveform panel. Everything is computed in the browser from the parsed file.

type Channel = "breathing" | "ldc_L_uH" | "ldc_freq_hz" | "a0_raw" | "vbat_v";
const CHANNELS: Record<Channel, { label: string; unit: string; digits: number }> = {
  breathing: { label: "Breathing (filtered, with detected breaths)", unit: "µH", digits: 4 },
  ldc_L_uH: { label: "Belt inductance", unit: "µH", digits: 5 },
  ldc_freq_hz: { label: "Sensor frequency", unit: "Hz", digits: 1 },
  a0_raw: { label: "Auxiliary input a0 (debug only)", unit: "counts", digits: 0 },
  vbat_v: { label: "Battery voltage", unit: "V", digits: 3 },
};
const ZOOMS = [
  { label: "Whole recording", span_ms: Infinity },
  { label: "5 min", span_ms: 5 * 60_000 },
  { label: "30 s", span_ms: 30_000 },
  { label: "5 s", span_ms: 5_000 },
] as const;
const MAX_POINTS = 3000;

const MARKERS_MAX_SPAN_MS = 10 * 60_000; // breath markers only when zoomed to <= 10 min

export function DeviceTrace({
  recording,
  analysis = null,
  selection = null,
  onSelect,
}: {
  recording: DeviceRecording;
  analysis?: BreathingAnalysis | null;
  /** Highlighted stretch, seconds since start. */
  selection?: [number, number] | null;
  /** Called when the user drags across the chart (seconds since start). */
  onSelect?: (startS: number, endS: number) => void;
}) {
  const { columns, stats, meta } = recording;
  const hasSensor = stats.sensor_rows > 0;
  const hasBattery = recording.battery !== null;
  // Why a channel can't be shown for this file, or null if it can.
  const missingReason = (c: Channel): string | null =>
    c === "breathing"
      ? analysis
        ? null
        : "no analysis"
      : c === "vbat_v"
        ? hasBattery
          ? null
          : "not logged"
        : c === "a0_raw" || hasSensor
          ? null
          : "no sensor data";
  const totalMs = columns.elapsed_ms.length ? columns.elapsed_ms[columns.elapsed_ms.length - 1] + 1 : 0;

  const [channel, setChannel] = useState<Channel>(analysis ? "breathing" : hasSensor ? "ldc_L_uH" : "a0_raw");

  // The filtered signal lives on the even sample grid: sample k is at k / fs seconds.
  const gridMs = useMemo(
    () => (analysis ? Float64Array.from({ length: analysis.n_samples }, (_, k) => (k * 1000) / analysis.fs_hz) : null),
    [analysis],
  );
  const [timeMode, setTimeMode] = useState<"elapsed" | "clock">("elapsed");
  const [spanMs, setSpanMs] = useState(totalMs);
  const [startMs, setStartMs] = useState(0);
  const endMs = Math.min(totalMs, startMs + spanMs);

  const points = useMemo(
    () =>
      channel === "breathing" && analysis && gridMs
        ? tracePoints(gridMs, analysis.filtered, startMs, endMs, MAX_POINTS)
        : tracePoints(columns.elapsed_ms, columns[channel === "breathing" ? "ldc_L_uH" : channel], startMs, endMs, MAX_POINTS),
    [columns, channel, startMs, endMs, analysis, gridMs],
  );
  const data: uPlot.AlignedData = useMemo(() => [points.x, points.y], [points]);

  const formatX = (seconds: number) =>
    timeMode === "clock" ? (deviceClockTime(meta.start_local, seconds) ?? formatElapsed(seconds)) : formatElapsed(seconds);

  const info = CHANNELS[channel];
  const makeOptions = (theme: ChartTheme, width: number): uPlot.Options => ({
    width,
    height: 260,
    cursor: { drag: { x: Boolean(onSelect), y: false, setScale: false }, points: { show: false } },
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
    plugins: [
      // Per-minute signal quality from the analysis (poor / no signal shaded, like the night view).
      ...(analysis
        ? [qualityShading(analysis.quality.map((w) => w.start_s), analysis.quality.map((w) => w.label), theme)]
        : []),
      // Notes typed during recording ("# mark" lines) and the dragged selection.
      markerPlugin(
        [
          ...recording.marks
            .filter((m) => m.elapsed_ms !== null)
            .map((m, i) => ({ x_start: (m.elapsed_ms ?? 0) / 1000, x_end: null, label: `M${i + 1}` })),
          ...(selection ? [{ x_start: selection[0], x_end: selection[1], label: "sel", active: true }] : []),
        ],
        theme.annotation,
      ),
      ...(channel === "breathing" && analysis && endMs - startMs <= MARKERS_MAX_SPAN_MS
        ? [
            breathMarkersPlugin(
              analysis.breaths.peak_idx.map((k) => ({ x: k / analysis.fs_hz, y: analysis.filtered[k] })),
              analysis.breaths.trough_idx.map((k) => ({ x: k / analysis.fs_hz, y: analysis.filtered[k] })),
              theme.series[1],
            ),
          ]
        : []),
    ],
    hooks: onSelect ? pickHooks((a, b) => b !== null && onSelect(Math.min(a, b), Math.max(a, b))) : {},
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
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm print:hidden">
        <label className="flex items-center gap-2">
          <span className="text-muted">Signal</span>
          <select
            value={channel}
            onChange={(e) => setChannel(e.target.value as Channel)}
            className="rounded-md border border-border bg-background px-2 py-1"
          >
            {(Object.keys(CHANNELS) as Channel[]).map((c) => {
              const missing = missingReason(c);
              return (
                <option key={c} value={c} disabled={missing !== null}>
                  {CHANNELS[c].label}
                  {missing ? ` (${missing})` : ""}
                </option>
              );
            })}
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

      <div className="flex flex-wrap items-center gap-2 print:hidden">
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

      {analysis && <QualityLegend />}
      {/* Rebuild when the axis formatting or series label changes. */}
      <UPlotChart
        data={data}
        height={260}
        makeOptions={makeOptions}
        deps={[channel, timeMode, JSON.stringify(selection), endMs - startMs <= MARKERS_MAX_SPAN_MS]}
      />
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
