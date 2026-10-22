"use client";

import { useEffect, useRef, useSyncExternalStore } from "react";
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";

// A thin React wrapper around uPlot.
//
// Why uPlot: it draws tens of thousands of points on a <canvas> quickly and is ~50 KB,
// which suits long overnight signals. The trade-off is that it's not a React library,
// so this component bridges the two: create the chart in an effect, destroy it on cleanup.

export interface ChartTheme {
  grid: string;
  axis: string;
  text: string;
  series: [string, string, string, string];
  warning: string;
  neutral: string;
}

/** Read the color tokens from globals.css (canvas drawing can't use CSS variables directly). */
export function readChartTheme(): ChartTheme {
  const css = getComputedStyle(document.documentElement);
  const v = (name: string) => css.getPropertyValue(name).trim();
  return {
    grid: v("--chart-grid"),
    axis: v("--chart-axis"),
    text: v("--muted"),
    series: [v("--chart-series-1"), v("--chart-series-2"), v("--chart-series-3"), v("--chart-series-4")],
    warning: v("--status-warning"),
    neutral: v("--status-neutral"),
  };
}

// Re-render charts when the OS switches between light and dark.
const darkQuery = "(prefers-color-scheme: dark)";
function subscribeColorScheme(onChange: () => void) {
  const mq = window.matchMedia(darkQuery);
  mq.addEventListener("change", onChange);
  return () => mq.removeEventListener("change", onChange);
}
export function useColorScheme(): "light" | "dark" | null {
  return useSyncExternalStore(
    subscribeColorScheme,
    () => (window.matchMedia(darkQuery).matches ? "dark" : "light"),
    () => null,
  );
}

/** Standard axis styling: muted text, hairline grid, no tick marks. */
export function axisStyle(theme: ChartTheme, extra: Partial<uPlot.Axis> = {}): uPlot.Axis {
  return {
    stroke: theme.text,
    grid: { stroke: theme.grid, width: 1 },
    ticks: { show: false },
    font: "12px system-ui, sans-serif",
    labelFont: "12px system-ui, sans-serif",
    ...extra,
  };
}

interface Props {
  /** Builds the uPlot options. Called again whenever `deps` or the color scheme change. */
  makeOptions: (theme: ChartTheme, width: number) => uPlot.Options;
  data: uPlot.AlignedData;
  height: number;
  /** Values that should trigger rebuilding the chart (e.g. which series are shown). */
  deps?: readonly unknown[];
  className?: string;
}

export function UPlotChart({ makeOptions, data, height, deps = [], className }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<uPlot | null>(null);
  const scheme = useColorScheme();

  // Create (or re-create) the chart.
  useEffect(() => {
    const el = containerRef.current;
    if (!el || scheme === null) return;
    const width = Math.max(200, el.clientWidth);
    const chart = new uPlot({ ...makeOptions(readChartTheme(), width), height }, data, el);
    chartRef.current = chart;

    // Keep the chart as wide as its container (window resizes, sidebar changes, printing).
    const observer = new ResizeObserver(() => {
      chart.setSize({ width: Math.max(200, el.clientWidth), height });
    });
    observer.observe(el);
    return () => {
      observer.disconnect();
      chart.destroy();
      chartRef.current = null;
    };
    // `data` is handled by the next effect, so new data doesn't rebuild the whole chart.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scheme, height, ...deps]);

  // New data for an existing chart: just swap it in.
  useEffect(() => {
    chartRef.current?.setData(data);
  }, [data]);

  return <div ref={containerRef} className={className} />;
}
