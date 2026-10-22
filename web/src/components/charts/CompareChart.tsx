"use client";

import { useMemo, useState } from "react";
import type uPlot from "uplot";
import { LocalTime } from "@/components/LocalTime";
import type { MinuteMetrics } from "@/lib/data/types";
import { axisStyle, type ChartTheme, UPlotChart } from "./UPlotChart";

// Overlay 2-3 nights, aligned by time since the recording started (not clock time),
// so "2 hours in" lines up across nights that began at different times.

export interface CompareNight {
  recording_id: string;
  start_utc: string;
  /** Fixed color slot (0-3) for this night, so its color never changes with the selection. */
  color_slot: number;
  metrics: MinuteMetrics;
}

const MAX_SELECTED = 3;
const SMOOTH_MINUTES = 5;

type Metric = "resp_rate_bpm" | "amplitude_rel";
const METRICS: Record<Metric, { label: string; unit: string; digits: number; range: [number, number] }> = {
  resp_rate_bpm: { label: "Respiratory rate", unit: "bpm", digits: 1, range: [5, 35] },
  amplitude_rel: { label: "Relative amplitude", unit: "×", digits: 2, range: [0, 1.6] },
};

/** Centered rolling mean that skips missing minutes (null stays null if all are missing). */
function rollingMean(values: (number | null)[], window: number): (number | null)[] {
  const half = Math.floor(window / 2);
  return values.map((_, i) => {
    let sum = 0;
    let n = 0;
    for (let j = i - half; j <= i + half; j++) {
      const v = values[j];
      if (v != null) {
        sum += v;
        n++;
      }
    }
    return values[i] == null || n === 0 ? null : sum / n;
  });
}

export function CompareChart({ nights }: { nights: CompareNight[] }) {
  // Default: the two most recent nights.
  const [selected, setSelected] = useState<string[]>(() =>
    nights.slice(-2).map((n) => n.recording_id),
  );
  const [metric, setMetric] = useState<Metric>("resp_rate_bpm");
  const [smooth, setSmooth] = useState(true);

  const shown = nights.filter((n) => selected.includes(n.recording_id));

  function toggle(id: string) {
    setSelected((cur) =>
      cur.includes(id)
        ? cur.filter((x) => x !== id)
        : cur.length >= MAX_SELECTED
          ? cur
          : [...cur, id],
    );
  }

  const data: uPlot.AlignedData = useMemo(() => {
    const longest = Math.max(0, ...shown.map((n) => n.metrics.minute_index.length));
    const xs = Array.from({ length: longest }, (_, i) => i / 60); // hours since start
    const series = shown.map((n) => {
      const raw = n.metrics[metric];
      const values = smooth ? rollingMean(raw, SMOOTH_MINUTES) : raw;
      return xs.map((_, i) => values[i] ?? null);
    });
    return [xs, ...series];
  }, [shown, metric, smooth]);

  const info = METRICS[metric];
  const makeOptions = (theme: ChartTheme, width: number): uPlot.Options => ({
    width,
    height: 300,
    cursor: { drag: { x: false, y: false }, points: { size: 8 } },
    scales: { x: { time: false }, y: { range: info.range } },
    series: [
      { label: "Elapsed", value: (_u, v) => (v == null ? "" : formatElapsed(v)) },
      ...shown.map((n) => ({
        label: nightLabel(n.start_utc),
        stroke: theme.series[n.color_slot % theme.series.length],
        width: 2,
        points: { show: false },
        value: (_u: uPlot, v: number | null) =>
          v == null ? "—" : `${v.toFixed(info.digits)} ${info.unit}`,
      })),
    ],
    axes: [
      axisStyle(theme, { values: (_u, ticks) => ticks.map((h) => `${h} h`) }),
      axisStyle(theme, { size: 48 }),
    ],
  });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-6">
        <fieldset className="flex flex-wrap gap-3">
          <legend className="mb-1 text-sm text-muted">Nights (up to {MAX_SELECTED})</legend>
          {nights.map((n) => {
            const checked = selected.includes(n.recording_id);
            return (
              <label key={n.recording_id} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={checked}
                  disabled={!checked && selected.length >= MAX_SELECTED}
                  onChange={() => toggle(n.recording_id)}
                />
                <span
                  className="inline-block h-0.5 w-4"
                  style={{ background: `var(--chart-series-${(n.color_slot % 4) + 1})` }}
                  aria-hidden
                />
                <LocalTime iso={n.start_utc} format="date" />
              </label>
            );
          })}
        </fieldset>

        <fieldset className="flex gap-3">
          <legend className="mb-1 text-sm text-muted">Metric</legend>
          {(Object.keys(METRICS) as Metric[]).map((m) => (
            <label key={m} className="flex items-center gap-2 text-sm">
              <input type="radio" name="metric" checked={metric === m} onChange={() => setMetric(m)} />
              {METRICS[m].label}
            </label>
          ))}
        </fieldset>

        <label className="flex items-center gap-2 self-end text-sm">
          <input type="checkbox" checked={smooth} onChange={(e) => setSmooth(e.target.checked)} />
          {SMOOTH_MINUTES}-min average
        </label>
      </div>

      {shown.length === 0 ? (
        <p className="rounded-lg border border-border p-8 text-center text-sm text-muted">
          Select at least one night.
        </p>
      ) : (
        <figure>
          <figcaption className="text-sm font-medium">
            {info.label} ({info.unit}) by hours since recording start
          </figcaption>
          {/* Rebuild the chart when the set of series changes (uPlot series are fixed at creation). */}
          <UPlotChart
            data={data}
            height={300}
            makeOptions={makeOptions}
            deps={[selected.join(","), metric]}
          />
        </figure>
      )}
    </div>
  );
}

function formatElapsed(hours: number): string {
  const h = Math.floor(hours);
  const m = Math.round((hours - h) * 60);
  return `${h} h ${String(m).padStart(2, "0")} min`;
}

function nightLabel(iso: string): string {
  // uPlot legend labels are plain strings; this runs only in the browser, so local time is right.
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(new Date(iso));
}
