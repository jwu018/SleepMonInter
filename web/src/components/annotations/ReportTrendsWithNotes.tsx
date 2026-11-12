"use client";

import { NightTrends } from "@/components/charts/NightTrends";
import { useAnnotations } from "@/lib/annotations/store";
import { categoryLabel } from "@/lib/annotations/types";
import type { MinuteMetrics } from "@/lib/data/types";
import { formatSpan } from "./AnnotationPanel";

// Print report: trend charts with the numbered note markers, followed by the list of notes.
// Notes come from this browser's storage, so this part renders on the client.
export function ReportTrendsWithNotes({
  recordingId,
  startUtc,
  metrics,
}: {
  recordingId: string;
  startUtc: string;
  metrics: MinuteMetrics;
}) {
  const annotations = useAnnotations(recordingId);
  const startS = Date.parse(startUtc) / 1000;
  const markers = annotations.map((a, i) => ({
    x_start: startS + a.start_ms / 1000,
    x_end: a.end_ms === null ? null : startS + a.end_ms / 1000,
    label: String(i + 1),
  }));

  return (
    <>
      <NightTrends startUtc={startUtc} metrics={metrics} markers={markers} height={150} />
      <section className="break-inside-avoid">
        <h2 className="mb-1 text-sm font-semibold">Clinician notes</h2>
        {annotations.length === 0 ? (
          <p className="text-sm text-muted">None.</p>
        ) : (
          <table className="w-full text-sm">
            <tbody>
              {annotations.map((a, i) => (
                <tr key={a.id} className="border-b border-border align-top">
                  <td className="w-8 py-1 font-semibold">{i + 1}</td>
                  <td className="w-44 py-1 tabular">{formatSpan(startUtc, a.start_ms, a.end_ms)}</td>
                  <td className="w-32 py-1">{categoryLabel(a.category)}</td>
                  <td className="py-1">
                    {a.note || "—"}
                    <span className="block text-xs text-muted">{a.author_email}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  );
}
