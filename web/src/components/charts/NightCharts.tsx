"use client";

import { useMemo, useState } from "react";
import { AnnotationPanel, type PendingPick } from "@/components/annotations/AnnotationPanel";
import { useAnnotations } from "@/lib/annotations/store";
import type { MinuteMetrics } from "@/lib/data/types";
import type { ChartMarker } from "./markerPlugin";
import { NightTrends } from "./NightTrends";
import { WaveformPanel } from "./WaveformPanel";

// Holds the state the night view's panels share: where the waveform should jump to, the
// moment/stretch just picked for a new note, and the saved notes drawn on every chart.
export function NightCharts(props: {
  recordingId: string;
  startUtc: string;
  durationMs: number;
  metrics: MinuteMetrics;
  authorEmail: string;
}) {
  const [focusMs, setFocusMs] = useState<number | null>(null);
  const [pending, setPending] = useState<PendingPick | null>(null);
  const annotations = useAnnotations(props.recordingId);
  const startS = Date.parse(props.startUtc) / 1000;

  // Markers in ms since start. The pending pick is drawn too (labelled "+") so the user
  // sees exactly what they're about to annotate.
  const markersMs: ChartMarker[] = useMemo(() => {
    const saved = annotations.map((a, i) => ({ x_start: a.start_ms, x_end: a.end_ms, label: String(i + 1) }));
    return pending ? [...saved, { x_start: pending.start_ms, x_end: pending.end_ms, label: "+", active: true }] : saved;
  }, [annotations, pending]);
  const markersS = useMemo(
    () =>
      markersMs.map((m) => ({
        ...m,
        x_start: startS + m.x_start / 1000,
        x_end: m.x_end === null ? null : startS + m.x_end / 1000,
      })),
    [markersMs, startS],
  );

  function pick(startMs: number, endMs: number | null) {
    const clampMs = (ms: number) => Math.round(Math.min(props.durationMs, Math.max(0, ms)));
    setPending({ start_ms: clampMs(startMs), end_ms: endMs === null ? null : clampMs(endMs) });
  }

  return (
    <div className="grid gap-8 xl:grid-cols-[1fr_300px]">
      <div className="min-w-0 space-y-8">
        <section className="space-y-2">
          <h2 className="text-lg font-semibold">Overnight trends</h2>
          <NightTrends
            startUtc={props.startUtc}
            metrics={props.metrics}
            markers={markersS}
            onPick={(a, b) => {
              pick((a - startS) * 1000, b === null ? null : (b - startS) * 1000);
              setFocusMs((a - startS) * 1000);
            }}
          />
        </section>
        <section className="space-y-2">
          <h2 className="text-lg font-semibold">Raw waveform</h2>
          <WaveformPanel
            recordingId={props.recordingId}
            startUtc={props.startUtc}
            durationMs={props.durationMs}
            focusMs={focusMs}
            markers={markersMs}
            onPick={pick}
          />
        </section>
      </div>
      <aside>
        <AnnotationPanel
          recordingId={props.recordingId}
          startUtc={props.startUtc}
          authorEmail={props.authorEmail}
          pending={pending}
          onClearPending={() => setPending(null)}
          onJump={(ms) => setFocusMs(ms)}
        />
      </aside>
    </div>
  );
}
