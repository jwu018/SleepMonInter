import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { NightTrends } from "@/components/charts/NightTrends";
import { LocalTime } from "@/components/LocalTime";
import { PrintButton } from "@/components/PrintButton";
import { BlockSkeleton } from "@/components/Skeleton";
import { getRecording } from "@/lib/data";
import { estimateBattery, formatDuration, formatNumber } from "@/lib/format";

// Print-optimized one-page summary of a night. On screen it looks like a document;
// `print:hidden` removes the buttons and navigation from the printout.
export default function ReportPage({ params }: PageProps<"/recordings/[recordingId]/report">) {
  return (
    <Suspense fallback={<BlockSkeleton height={700} />}>
      <Report params={params} />
    </Suspense>
  );
}

async function Report({ params }: { params: PageProps<"/recordings/[recordingId]/report">["params"] }) {
  const { recordingId } = await params;
  const rec = await getRecording(recordingId);
  if (!rec) notFound();
  const battery = estimateBattery(rec.battery_start_mv, rec.battery_end_mv, rec.duration_min);

  const rows: [string, string][] = [
    ["Study code", rec.study_code],
    ["Device", rec.device_id],
    ["Duration", formatDuration(rec.duration_min)],
    ["Median respiratory rate", `${formatNumber(rec.median_resp_rate_bpm)} bpm`],
    ["Mean relative amplitude", `${formatNumber(rec.mean_amplitude_rel, 2)} ×`],
    [
      "Signal quality",
      `${formatNumber(rec.pct_good, 0)}% good · ${formatNumber(rec.pct_poor, 0)}% poor · ${formatNumber(rec.pct_no_signal, 0)}% no signal`,
    ],
    ["Data gaps (> 1 s)", String(rec.gap_count)],
    [
      "Battery (end of recording)",
      `${(rec.battery_end_mv / 1000).toFixed(2)} V · ≈ ${formatNumber(battery.remaining_hours, 1)} h left`,
    ],
  ];

  return (
    <article className="mx-auto max-w-3xl space-y-6">
      <div className="flex items-center justify-between print:hidden">
        <Link href={`/recordings/${rec.recording_id}`} className="text-sm text-accent hover:underline">
          ← Back to night view
        </Link>
        <PrintButton />
      </div>

      <header className="border-b border-border pb-3">
        <p className="text-xs uppercase tracking-wide text-muted">Night Night · overnight respiratory summary</p>
        <h1 className="text-2xl font-semibold">
          {rec.study_code} · night of <LocalTime iso={rec.start_utc} format="date" />
        </h1>
        <p className="text-sm text-muted">
          <LocalTime iso={rec.start_utc} format="datetime" /> – <LocalTime iso={rec.end_utc} format="datetime" />
        </p>
      </header>

      <table className="w-full text-sm">
        <tbody>
          {rows.map(([label, value]) => (
            <tr key={label} className="border-b border-border">
              <th className="w-1/3 py-1.5 text-left font-normal text-muted">{label}</th>
              <td className="tabular py-1.5">{value}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <NightTrends startUtc={rec.start_utc} metrics={rec.metrics} height={150} />

      <footer className="border-t border-border pt-2 text-xs text-muted">
        Prototype: synthetic data only, not for clinical use. Amplitude is relative to this
        night&apos;s median breath and is not a lung volume.
      </footer>
    </article>
  );
}
