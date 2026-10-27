import { Suspense } from "react";
import { BlockSkeleton } from "@/components/Skeleton";
import { UploadWorkspace } from "@/components/upload/UploadWorkspace";
import { listPatients } from "@/lib/data";

// Upload microSD recordings. For the prototype, files are read in the browser only and
// kept in memory until the tab closes: they're never sent to or stored on the server.
// (Server-side upload and processing come with the backend.)
export default function UploadPage() {
  return (
    <section className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Upload recordings</h1>
        <p className="text-sm text-muted">
          Read recordings straight from the device&apos;s microSD card to check what was captured.
        </p>
      </div>

      <div className="rounded-md border border-border bg-surface px-4 py-3 text-sm">
        <strong>Stays on this computer.</strong> Files are read in this browser tab only. Nothing is
        uploaded to a server, and everything is cleared when you close or reload the tab.
        Breathing analysis (rate and amplitude) isn&apos;t run on uploads yet.
      </div>

      <Suspense fallback={<BlockSkeleton height={240} />}>
        <Workspace />
      </Suspense>
    </section>
  );
}

async function Workspace() {
  // Study codes for the optional "tag to a patient" dropdown (needs a signed-in user).
  const patients = await listPatients();
  return <UploadWorkspace studyCodes={patients.map((p) => p.study_code)} />;
}
