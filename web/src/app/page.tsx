import Link from "next/link";
import { Suspense } from "react";
import { LocalTime } from "@/components/LocalTime";
import { TableSkeleton } from "@/components/Skeleton";
import { listPatients } from "@/lib/data";

// Patient list (home page).
// The heading is static and renders instantly; the table reads data (and, soon, the
// login cookie), so it streams in behind a <Suspense> boundary. That's the pattern
// Next.js 16 requires with cacheComponents turned on.
export default function PatientsPage() {
  return (
    <section className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Patients</h1>
        <p className="text-sm text-muted">
          Patients are identified by study code only. Select one to see their nights.
        </p>
      </div>
      <Suspense fallback={<TableSkeleton rows={3} />}>
        <PatientTable />
      </Suspense>
    </section>
  );
}

async function PatientTable() {
  const patients = await listPatients();
  if (patients.length === 0) {
    return <p className="text-muted">No patients yet.</p>;
  }
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-left text-sm">
        <thead className="bg-surface text-muted">
          <tr>
            <th className="px-4 py-2 font-medium">Study code</th>
            <th className="px-4 py-2 font-medium">Device</th>
            <th className="px-4 py-2 text-right font-medium">Nights recorded</th>
            <th className="px-4 py-2 font-medium">Last night</th>
          </tr>
        </thead>
        <tbody>
          {patients.map((p) => (
            <tr key={p.study_code} className="border-t border-border hover:bg-surface">
              <td className="px-4 py-3 font-medium">
                <Link href={`/patients/${p.study_code}`} className="text-accent hover:underline">
                  {p.study_code}
                </Link>
              </td>
              <td className="px-4 py-3 text-muted">{p.device_id}</td>
              <td className="tabular px-4 py-3 text-right">{p.recording_count}</td>
              <td className="px-4 py-3">
                {p.last_recording_start_utc ? (
                  <LocalTime iso={p.last_recording_start_utc} format="date" />
                ) : (
                  "—"
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
