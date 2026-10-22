import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { LocalTime } from "@/components/LocalTime";
import { TableSkeleton } from "@/components/Skeleton";
import { Sparkline } from "@/components/Sparkline";
import { getPatient } from "@/lib/data";
import { formatDuration, formatNumber } from "@/lib/format";

// Patient overview: every night for one patient, plus a mini trend of median RR per night.
export default function PatientPage({ params }: PageProps<"/patients/[studyCode]">) {
  return (
    <Suspense fallback={<TableSkeleton rows={4} />}>
      <PatientOverview params={params} />
    </Suspense>
  );
}

async function PatientOverview({ params }: { params: PageProps<"/patients/[studyCode]">["params"] }) {
  const { studyCode } = await params;
  const patient = await getPatient(studyCode);
  if (!patient) notFound();

  const nights = patient.recordings; // oldest first
  return (
    <section className="space-y-6">
      <div>
        <p className="text-sm text-muted">
          <Link href="/" className="hover:underline">
            Patients
          </Link>{" "}
          / {patient.study_code}
        </p>
        <h1 className="text-2xl font-semibold tracking-tight">{patient.study_code}</h1>
        <p className="text-sm text-muted">
          Device {patient.device_id} · {patient.recording_count} nights recorded
        </p>
      </div>

      <div className="flex flex-wrap items-end justify-between gap-4 rounded-lg border border-border bg-surface p-4">
        <div>
          <p className="text-sm font-medium">Median respiratory rate per night (bpm)</p>
          <p className="text-xs text-muted">Oldest to newest, one dot per night</p>
          <div className="mt-2">
            <Sparkline
              values={nights.map((n) => n.median_resp_rate_bpm)}
              label={`Median respiratory rate per night: ${nights
                .map((n) => formatNumber(n.median_resp_rate_bpm))
                .join(", ")} bpm`}
            />
          </div>
        </div>
        <Link
          href={`/patients/${patient.study_code}/compare`}
          className="rounded-md border border-border bg-background px-3 py-1.5 text-sm hover:bg-surface"
        >
          Compare nights →
        </Link>
      </div>

      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-left text-sm">
          <thead className="bg-surface text-muted">
            <tr>
              <th className="px-4 py-2 font-medium">Night of</th>
              <th className="px-4 py-2 font-medium">Duration</th>
              <th className="px-4 py-2 text-right font-medium">Median RR (bpm)</th>
              <th className="px-4 py-2 text-right font-medium">Good signal</th>
              <th className="px-4 py-2 text-right font-medium">Data gaps</th>
              <th className="px-4 py-2 text-right font-medium">Battery at end</th>
            </tr>
          </thead>
          <tbody>
            {[...nights].reverse().map((n) => (
              <tr key={n.recording_id} className="border-t border-border hover:bg-surface">
                <td className="px-4 py-3 font-medium">
                  <Link href={`/recordings/${n.recording_id}`} className="text-accent hover:underline">
                    <LocalTime iso={n.start_utc} format="date" />
                  </Link>
                </td>
                <td className="px-4 py-3">{formatDuration(n.duration_min)}</td>
                <td className="tabular px-4 py-3 text-right">{formatNumber(n.median_resp_rate_bpm)}</td>
                <td className="tabular px-4 py-3 text-right">{formatNumber(n.pct_good, 0)}%</td>
                <td className="tabular px-4 py-3 text-right">{n.gap_count}</td>
                <td className="tabular px-4 py-3 text-right">{(n.battery_end_mv / 1000).toFixed(2)} V</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
