"use client";

import { useState } from "react";
import { PrintButton } from "@/components/PrintButton";
import { StatTile } from "@/components/StatTile";
import { describeIssues, type DeviceRecording } from "@/lib/device/parseDeviceCsv";
import { formatElapsed } from "@/lib/device/trace";
import type { BreathingAnalysis } from "@/lib/processing/breathing";
import { BreathingPanel } from "./BreathingPanel";
import { DeviceTrace } from "./DeviceTrace";
import { BatteryIcon } from "./BatteryIcon";
import { RecordingBadge } from "./RecordingBadge";

// Detail view of one uploaded recording: what the file contains and whether it's intact.
// Plus the breathing analysis (breath count, rate, pauses) for Test 2.
export function UploadedRecordingView({
  name,
  recording,
  analysis,
  analysisError,
  studyCode,
  onBack,
}: {
  name: string;
  recording: DeviceRecording;
  analysis: BreathingAnalysis | null;
  analysisError: string | null;
  studyCode: string;
  onBack: () => void;
}) {
  // A stretch dragged on the chart, in seconds since switch-on.
  const [selection, setSelection] = useState<[number, number] | null>(null);
  const { meta, stats, stop, drift_checks, battery } = recording;
  const issues = describeIssues(recording);
  const worstDrift = drift_checks.reduce<number | null>(
    (worst, d) => (d.drift_ms == null ? worst : Math.max(worst ?? 0, Math.abs(d.drift_ms))),
    null,
  );

  const details: [string, string][] = [
    ["Device clock at start", meta.start_local ?? "—"],
    ["Firmware", meta.firmware ?? "—"],
    ["Device ID", meta.device_id ?? "not in file"],
    ["Real-time clock", meta.rtc ?? "—"],
    ["Sample rate", meta.sample_rate_hz ? `${meta.sample_rate_hz} Hz` : "—"],
    ["Sensor", meta.sensor_status ?? "—"],
    ["Rows", stats.row_count.toLocaleString()],
    ["Longest gap between samples", `${stats.max_interval_ms} ms`],
    ["Rows with sensor error flags", stats.flagged_rows.toLocaleString()],
    ["Rows with amplitude warning only (normal on the belt)", stats.amplitude_warning_rows.toLocaleString()],
    ["Clock drift checks", drift_checks.length ? `${drift_checks.length} (worst ${worstDrift ?? "—"} ms)` : "none (written every 10 min)"],
    [
      "How it ended",
      stop
        ? `Stopped cleanly (${stop.reason ?? "no reason given"}); device counted ${stop.rows ?? "?"} rows, ${stop.missed_slots ?? "?"} missed`
        : "No stop line: the recording ended unexpectedly (e.g. power was cut)",
    ],
  ];

  return (
    <article className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <button type="button" onClick={onBack} className="text-sm text-accent hover:underline print:hidden">
            ← All uploaded recordings
          </button>
          <p className="hidden text-xs uppercase tracking-wide text-muted print:block">
            Night Night · trial recording summary
          </p>
          <h2 className="mt-1 text-xl font-semibold tracking-tight">{name}</h2>
          <p className="text-sm text-muted">{studyCode ? `Tagged ${studyCode}` : "Not tagged to a patient"}</p>
        </div>
        <div className="flex items-center gap-3">
          <RecordingBadge badge={issues.badge} />
          <span className="print:hidden">
            <PrintButton />
          </span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatTile label="Duration" value={formatElapsed(stats.duration_ms / 1000)} unit="m:ss" />
        <StatTile label="Sensor data" value={stats.sensor_rows > 0 ? "Yes" : "No"} />
        <StatTile label="Missed samples" value={stats.missed_samples} note="From jumps in the sample counter" />
        <StatTile label="Late samples" value={stats.late_samples} note="Gaps longer than 50 ms" />
      </div>

      <section className="flex flex-wrap items-center gap-6 rounded-lg border border-border bg-surface p-4">
        <BatteryIcon battery={battery} size="lg" />
        <div className="text-sm">
          <p className="font-semibold">Logger battery</p>
          <p className="text-xs text-muted">At end of recording, not live</p>
          {battery ? (
            <p className="mt-1">
              {battery.end_v !== null ? `${battery.end_v.toFixed(2)} V at end` : "No valid reading"}
              {battery.start_pct !== null && battery.end_pct !== null && (
                <span className="text-muted">
                  {" "}
                  · started at {battery.start_pct}% ({battery.start_v?.toFixed(2)} V), used {battery.start_pct - battery.end_pct}%
                </span>
              )}
            </p>
          ) : (
            <p className="mt-1 text-muted">This file has no battery columns (firmware before 0.5).</p>
          )}
          {battery?.end_pct !== null && battery?.end_pct !== undefined && battery.end_pct < 20 && (
            <p className="mt-1 font-medium">⚠ Low: charge or swap the battery before the next night.</p>
          )}
        </div>
      </section>

      {issues.notes.length > 0 && (
        <ul className="list-inside list-disc space-y-1 text-sm">
          {issues.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )}

      <section className="space-y-2">
        <h3 className="font-semibold">Breathing</h3>
        <BreathingPanel
          analysis={analysis}
          error={analysisError}
          selection={selection}
          onClearSelection={() => setSelection(null)}
        />
      </section>

      <section className="space-y-2">
        <h3 className="font-semibold">Signal</h3>
        <DeviceTrace
          recording={recording}
          analysis={analysis}
          selection={selection}
          onSelect={(a, b) => setSelection([a, b])}
        />
      </section>

      {recording.marks.length > 0 && (
        <section>
          <h3 className="mb-2 font-semibold">Marks typed during recording</h3>
          <ol className="space-y-1 text-sm">
            {recording.marks.map((m, i) => (
              <li key={`${m.datetime}-${i}`} className="flex gap-3">
                <span className="font-semibold text-annotation">M{i + 1}</span>
                <span className="tabular text-muted">
                  {m.elapsed_ms !== null ? formatElapsed(m.elapsed_ms / 1000) : m.datetime}
                </span>
                <span>{m.note || "(no text)"}</span>
              </li>
            ))}
          </ol>
        </section>
      )}

      <section>
        <h3 className="mb-2 font-semibold">File details</h3>
        <table className="w-full text-sm">
          <tbody>
            {details.map(([label, value]) => (
              <tr key={label} className="border-b border-border">
                <th className="w-1/3 py-1.5 pr-4 text-left font-normal text-muted">{label}</th>
                <td className="py-1.5">{value}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </article>
  );
}
