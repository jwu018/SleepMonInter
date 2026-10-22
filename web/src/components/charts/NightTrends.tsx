"use client";

import { useMemo } from "react";
import type uPlot from "uplot";
import type { MinuteMetrics, Quality } from "@/lib/data/types";
import { axisStyle, type ChartTheme, UPlotChart } from "./UPlotChart";

// Respiratory-rate and amplitude trends for one night, one point per minute.
// Two separate charts (never one chart with two y-axes) that share the time axis and a
// synced cursor, so hovering one shows the same minute in both.

const SYNC_KEY = "night-trends";

/**
 * uPlot plugin: before the series are drawn, shade every poor / no_signal minute.
 * Drawing in the "drawClear" hook puts the shading *behind* the lines.
 */
function qualityShading(xs: number[], quality: Quality[], theme: ChartTheme): uPlot.Plugin {
  return {
    hooks: {
      drawClear: (u) => {
        const { ctx } = u;
        const { top, height } = u.bbox;
        ctx.save();
        for (let i = 0; i < xs.length; i++) {
          const q = quality[i];
          if (q === "good") continue;
          const x0 = Math.round(u.valToPos(xs[i], "x", true));
          const x1 = Math.round(u.valToPos(xs[i] + 60, "x", true));
          ctx.fillStyle = q === "poor" ? theme.warning : theme.neutral;
          ctx.globalAlpha = q === "poor" ? 0.22 : 0.3;
          ctx.fillRect(x0, top, Math.max(1, x1 - x0), height);
        }
        ctx.restore();
      },
    },
  };
}

interface Props {
  startUtc: string;
  metrics: MinuteMetrics;
  /** Called with seconds-since-epoch when the user clicks a point in time. */
  onPickTime?: (unixSeconds: number) => void;
  height?: number;
}

export function NightTrends({ startUtc, metrics, onPickTime, height = 180 }: Props) {
  const startS = Date.parse(startUtc) / 1000;
  const xs = useMemo(
    () => metrics.minute_index.map((m) => startS + m * 60),
    [metrics, startS],
  );

  function makeOptions(
    label: string,
    unit: string,
    digits: number,
    range: uPlot.Range.MinMax,
  ) {
    return (theme: ChartTheme, width: number): uPlot.Options => ({
      width,
      height,
      cursor: {
        sync: { key: SYNC_KEY },
        drag: { x: false, y: false },
        points: { size: 8 },
      },
      scales: { x: { time: true }, y: { range } },
      series: [
        {},
        {
          label,
          stroke: theme.series[0],
          width: 2,
          points: { show: false },
          value: (_u, v, _s, idx) =>
            idx == null ? "—" : v == null ? "no signal" : `${v.toFixed(digits)} ${unit}`,
        },
      ],
      axes: [axisStyle(theme), axisStyle(theme, { size: 48 })],
      plugins: [qualityShading(xs, metrics.quality, theme)],
      hooks: onPickTime
        ? {
            ready: [
              (u) => {
                u.over.addEventListener("click", () => {
                  const idx = u.cursor.idx;
                  if (idx != null) onPickTime(xs[idx]);
                });
              },
            ],
          }
        : {},
    });
  }

  const rrData: uPlot.AlignedData = useMemo(() => [xs, metrics.resp_rate_bpm], [xs, metrics]);
  const ampData: uPlot.AlignedData = useMemo(() => [xs, metrics.amplitude_rel], [xs, metrics]);

  return (
    <div className="space-y-2">
      <QualityLegend />
      <figure>
        <figcaption className="text-sm font-medium">Respiratory rate (breaths/min)</figcaption>
        <UPlotChart
          data={rrData}
          height={height}
          makeOptions={makeOptions("Resp. rate", "bpm", 1, [5, 35])}
        />
      </figure>
      <figure>
        <figcaption className="text-sm font-medium">
          Relative amplitude (1.0 = this night&apos;s median breath depth)
        </figcaption>
        <UPlotChart
          data={ampData}
          height={height}
          makeOptions={makeOptions("Rel. amplitude", "×", 2, [0, 1.6])}
        />
      </figure>
    </div>
  );
}

/** Text legend for the shading: status colors never carry meaning on their own. */
export function QualityLegend() {
  return (
    <div className="flex flex-wrap gap-4 text-xs text-muted">
      <span className="flex items-center gap-1.5">
        <span className="inline-block h-3 w-3 rounded-sm bg-status-warning opacity-60" />
        Poor signal (motion, artifacts)
      </span>
      <span className="flex items-center gap-1.5">
        <span className="inline-block h-3 w-3 rounded-sm bg-status-neutral opacity-60" />
        No signal (band loose or data gap)
      </span>
    </div>
  );
}
