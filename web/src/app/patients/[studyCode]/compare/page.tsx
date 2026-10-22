import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { type CompareNight, CompareChart } from "@/components/charts/CompareChart";
import { BlockSkeleton } from "@/components/Skeleton";
import { getPatient, getRecording } from "@/lib/data";

// Compare nights: the server loads every night's per-minute metrics (small: ~500 numbers
// per night), and the client component handles selecting which ones to overlay.
export default function ComparePage({ params }: PageProps<"/patients/[studyCode]/compare">) {
  return (
    <Suspense fallback={<BlockSkeleton height={380} />}>
      <Compare params={params} />
    </Suspense>
  );
}

async function Compare({ params }: { params: PageProps<"/patients/[studyCode]/compare">["params"] }) {
  const { studyCode } = await params;
  const patient = await getPatient(studyCode);
  if (!patient) notFound();

  const details = await Promise.all(patient.recordings.map((r) => getRecording(r.recording_id)));
  const nights: CompareNight[] = details.flatMap((d, i) =>
    d ? [{ recording_id: d.recording_id, start_utc: d.start_utc, color_slot: i, metrics: d.metrics }] : [],
  );

  return (
    <section className="space-y-6">
      <div>
        <p className="text-sm text-muted">
          <Link href="/" className="hover:underline">
            Patients
          </Link>{" "}
          /{" "}
          <Link href={`/patients/${patient.study_code}`} className="hover:underline">
            {patient.study_code}
          </Link>{" "}
          / Compare
        </p>
        <h1 className="text-2xl font-semibold tracking-tight">Compare nights · {patient.study_code}</h1>
        <p className="text-sm text-muted">
          Nights are aligned by time since the recording started.
        </p>
      </div>
      <CompareChart nights={nights} />
    </section>
  );
}
