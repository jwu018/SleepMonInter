"use client";

import { StatTile } from "@/components/StatTile";
import { describeIssues, type DeviceRecording } from "@/lib/device/parseDeviceCsv";
import { formatElapsed } from "@/lib/device/trace";
import { DeviceTrace } from "./DeviceTrace";
import { RecordingBadge } from "./RecordingBadge";

// Detail view of one uploaded recording: what the file contains and whether it's intact.
// No breathing analysis yet (rate/amplitude processing comes later).
export function UploadedRecordingView({
  name,
  recording,
  studyCode,
  onBack,
}: {
  name: string;
  recording: DeviceRecording;
  studyCode: string;
  onBack: () => void;
}) {
  const { meta, stats, stop, drift_checks } = recording;
  const issues = describeIssues(recording);
  const worstDrift = drift_checks.reduce<number | null>(
    (worst, d) => (d.drift_ms == null ? worst : Math.max(worst ?? 0, Math.abs(d.drift_ms))),
    null,
  );

  const details: [string, string][] = [
    ["Device clock at start", meta.start_local ?? "—"],
    ["Firmware", meta.firmware ?? "—"],
    ["Real-time clock", meta.rtc ?? "—"],
    ["Sample rate", meta.sample_rate_hz ? `${meta.sample_rate_hz} Hz` : "—"],
    ["Sensor", meta.sensor_status ?? "—"],
    ["Rows", stats.row_count.toLocaleString()],
    ["Longest gap between samples", `${stats.max_interval_ms} ms`],
    ["Rows with sensor warning flags", stats.flagged_rows.toLocaleString()],
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
          <button type="button" onClick={onBack} className="text-sm text-accent hover:underline">
            ← All uploaded recordings
          </button>
          <h2 className="mt-1 text-xl font-semibold tracking-tight">{name}</h2>
          <p className="text-sm text-muted">{studyCode ? `Tagged ${studyCode}` : "Not tagged to a patient"}</p>
        </div>
        <RecordingBadge badge={issues.badge} />
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatTile label="Duration" value={formatElapsed(stats.duration_ms / 1000)} unit="m:ss" />
        <StatTile label="Sensor data" value={stats.sensor_rows > 0 ? "Yes" : "No"} />
        <StatTile label="Missed samples" value={stats.missed_samples} note="From jumps in the sample counter" />
        <StatTile label="Late samples" value={stats.late_samples} note="Gaps longer than 50 ms" />
      </div>

      {issues.notes.length > 0 && (
        <ul className="list-inside list-disc space-y-1 text-sm">
          {issues.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )}

      <section className="space-y-2">
        <h3 className="font-semibold">Signal</h3>
        <DeviceTrace recording={recording} />
      </section>

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
