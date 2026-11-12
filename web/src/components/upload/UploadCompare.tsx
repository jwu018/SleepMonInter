"use client";

import { useMemo, useState } from "react";
import type uPlot from "uplot";
import { axisStyle, type ChartTheme, UPlotChart } from "@/components/charts/UPlotChart";
import { PrintButton } from "@/components/PrintButton";
import { clockLabel } from "@/lib/clockAxis";
import type { DeviceRecording } from "@/lib/device/parseDeviceCsv";
import { formatElapsed, tracePoints } from "@/lib/device/trace";
import { type BreathingAnalysis, countCompleteBreaths } from "@/lib/processing/breathing";
import {
  alignSeries,
  breathByBreathRate,
  deviceStartAfterNoonS,
  medianBreathDepth,
  type XY,
} from "@/lib/processing/compare";

// Overlay 2-3 uploaded recordings: the breathing signals themselves (each scaled to its own
// median breath, so different belt fits are comparable) or breath-by-breath rate.

export interface CompareItem {
  id: string;
  name: string;
  recording: DeviceRecording;
  analysis: BreathingAnalysis;
  colorSlot: number;
}

type Metric = "signal" | "rate";
type Align = "elapsed" | "clock";
const ZOOMS = [
  { label: "Whole", span_s: Infinity },
  { label: "5 min", span_s: 300 },
  { label: "1 min", span_s: 60 },
  { label: "20 s", span_s: 20 },
] as const;
const MAX_POINTS_PER_SERIES = 1500;

export function UploadCompare({ items, onBack }: { items: CompareItem[]; onBack: () => void }) {
  const [metric, setMetric] = useState<Metric>("signal");
  const [align, setAlign] = useState<Align>("elapsed");
  const [spanS, setSpanS] = useState<number>(Infinity);
  const [startS, setStartS] = useState(0);

  // Where each recording starts on the shared axis (seconds).
  const offsets = useMemo(
    () =>
      items.map((it) =>
        align === "clock" ? (deviceStartAfterNoonS(it.recording.meta.start_local) ?? 0) : 0,
      ),
    [items, align],
  );
  const axisStart = Math.min(...offsets);
  const axisEnd = Math.max(...items.map((it, i) => offsets[i] + it.analysis.n_samples / it.analysis.fs_hz));
  const totalS = axisEnd - axisStart;
  const span = Math.min(spanS, totalS);
  const viewStart = axisStart + Math.min(startS, Math.max(0, totalS - span));
  const viewEnd = viewStart + span;

  const data: uPlot.AlignedData = useMemo(() => {
    const series: XY[] = items.map((it, i) => {
      const a = it.analysis;
      if (metric === "rate") {
        const r = breathByBreathRate(a.breaths, a.fs_hz, offsets[i]);
        const keep = r.x.map((x) => x >= viewStart && x <= viewEnd);
        return { x: r.x.filter((_, k) => keep[k]), y: r.y.filter((_, k) => keep[k]) };
      }
      const depth = medianBreathDepth(a.filtered, a.breaths);
      const scaled = a.filtered.map((v) => (Number.isFinite(depth) && depth > 0 ? v / depth : v));
      const gridMs = Float64Array.from({ length: a.n_samples }, (_, k) => (k * 1000) / a.fs_hz);
      const pts = tracePoints(
        gridMs,
        scaled,
        (viewStart - offsets[i]) * 1000,
        (viewEnd - offsets[i]) * 1000,
        MAX_POINTS_PER_SERIES,
      );
      return { x: pts.x.map((x) => x + offsets[i]), y: pts.y };
    });
    const { x, ys } = alignSeries(series);
    return [x, ...ys];
  }, [items, metric, offsets, viewStart, viewEnd]);

  const formatX = (s: number) => (align === "clock" ? clockLabel(s / 3600) : formatElapsed(s));
  const makeOptions = (theme: ChartTheme, width: number): uPlot.Options => ({
    width,
    height: 320,
    cursor: { drag: { x: false, y: false }, points: { size: 6 } },
    scales: { x: { time: false, min: viewStart, max: viewEnd } },
    series: [
      { label: align === "clock" ? "Device clock" : "Since switch-on", value: (_u, v) => (v == null ? "—" : formatX(v)) },
      ...items.map((it) => ({
        label: it.name,
        stroke: theme.series[it.colorSlot % theme.series.length],
        width: metric === "rate" ? 2 : 1.5,
        spanGaps: true,
        points: { show: metric === "rate", size: 5 },
        value: (_u: uPlot, v: number | null) =>
          v == null ? "—" : metric === "rate" ? `${v.toFixed(1)} /min` : `${v.toFixed(2)} ×`,
      })),
    ],
    axes: [
      axisStyle(theme, { values: (_u, ticks) => ticks.map(formatX) }),
      axisStyle(theme, { size: 56, label: metric === "rate" ? "breaths/min" : "× median breath" }),
    ],
  });

  return (
    <article className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <button type="button" onClick={onBack} className="text-sm text-accent hover:underline print:hidden">
            ← All uploaded recordings
          </button>
          <h2 className="text-xl font-semibold tracking-tight">Compare recordings</h2>
          <p className="hidden text-sm print:block">Night Night · trial comparison</p>
        </div>
        <div className="print:hidden">
          <PrintButton />
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm print:hidden">
        <fieldset className="flex gap-3">
          <legend className="sr-only">Show</legend>
          <span className="text-muted">Show</span>
          <label className="flex items-center gap-1">
            <input type="radio" checked={metric === "signal"} onChange={() => setMetric("signal")} />
            Breathing signal
          </label>
          <label className="flex items-center gap-1">
            <input type="radio" checked={metric === "rate"} onChange={() => setMetric("rate")} />
            Breath-by-breath rate
          </label>
        </fieldset>
        <fieldset className="flex gap-3">
          <legend className="sr-only">Align by</legend>
          <span className="text-muted">Align by</span>
          <label className="flex items-center gap-1">
            <input type="radio" checked={align === "elapsed"} onChange={() => { setAlign("elapsed"); setStartS(0); }} />
            Switch-on
          </label>
          <label className="flex items-center gap-1">
            <input type="radio" checked={align === "clock"} onChange={() => { setAlign("clock"); setStartS(0); }} />
            Device clock
          </label>
        </fieldset>
        <div role="group" aria-label="Zoom" className="flex overflow-hidden rounded-md border border-border">
          {ZOOMS.map((z) => (
            <button
              key={z.label}
              type="button"
              aria-pressed={Math.min(z.span_s, totalS) === span}
              disabled={z.span_s !== Infinity && z.span_s >= totalS}
              onClick={() => setSpanS(z.span_s)}
              className={`px-3 py-1 disabled:opacity-40 ${Math.min(z.span_s, totalS) === span ? "bg-accent text-background" : "hover:bg-surface"}`}
            >
              {z.label}
            </button>
          ))}
        </div>
        {span < totalS && (
          <input
            type="range"
            aria-label="Position"
            min={0}
            max={Math.max(0, totalS - span)}
            step={Math.max(0.5, span / 40)}
            value={viewStart - axisStart}
            onChange={(e) => setStartS(Number(e.target.value))}
            className="w-48 accent-[var(--accent)]"
          />
        )}
      </div>

      <figure>
        <figcaption className="text-sm font-medium">
          {metric === "signal"
            ? "Breathing signal, each scaled to its own median breath (1 = a typical breath)"
            : "Breaths per minute, breath by breath (60 ÷ time between breaths)"}
        </figcaption>
        <UPlotChart data={data} height={320} makeOptions={makeOptions} deps={[metric, align, viewStart, viewEnd, items.length]} />
      </figure>

      <table className="w-full text-sm">
        <thead className="text-left text-muted">
          <tr>
            <th className="py-1 font-medium">Recording</th>
            <th className="py-1 font-medium">Device clock at start</th>
            <th className="py-1 text-right font-medium">Duration</th>
            <th className="py-1 text-right font-medium">Complete breaths</th>
            <th className="py-1 text-right font-medium">Rate</th>
          </tr>
        </thead>
        <tbody>
          {items.map((it) => {
            const a = it.analysis;
            const dur = a.n_samples / a.fs_hz;
            const n = countCompleteBreaths(a.breaths, a.fs_hz, 0, dur);
            return (
              <tr key={it.id} className="border-t border-border">
                <td className="py-1">
                  <span
                    className="mr-2 inline-block h-0.5 w-4 align-middle"
                    style={{ background: `var(--chart-series-${(it.colorSlot % 4) + 1})` }}
                    aria-hidden
                  />
                  {it.name}
                </td>
                <td className="py-1">{it.recording.meta.start_local ?? "—"}</td>
                <td className="tabular py-1 text-right">{formatElapsed(dur)}</td>
                <td className="tabular py-1 text-right">{n}</td>
                <td className="tabular py-1 text-right">{dur > 0 ? ((n / dur) * 60).toFixed(1) : "—"} /min</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="text-xs text-muted">
        Counts here cover each whole recording (no settling trim). Use each recording&apos;s own page
        to set the trim for Test 2.
      </p>
    </article>
  );
}
