"use client";

import { useState } from "react";
import type { MinuteMetrics } from "@/lib/data/types";
import { NightTrends } from "./NightTrends";
import { WaveformPanel } from "./WaveformPanel";

// Holds the one piece of state the two panels share: the moment the user clicked on the
// trend charts, which the waveform panel then zooms to.
export function NightCharts(props: {
  recordingId: string;
  startUtc: string;
  durationMs: number;
  metrics: MinuteMetrics;
}) {
  const [focusMs, setFocusMs] = useState<number | null>(null);
  const startS = Date.parse(props.startUtc) / 1000;

  return (
    <div className="space-y-8">
      <section className="space-y-2">
        <h2 className="text-lg font-semibold">Overnight trends</h2>
        <NightTrends
          startUtc={props.startUtc}
          metrics={props.metrics}
          onPickTime={(unixS) => setFocusMs((unixS - startS) * 1000 + 30_000)}
        />
      </section>
      <section className="space-y-2">
        <h2 className="text-lg font-semibold">Raw waveform</h2>
        <WaveformPanel
          recordingId={props.recordingId}
          startUtc={props.startUtc}
          durationMs={props.durationMs}
          focusMs={focusMs}
        />
      </section>
    </div>
  );
}
