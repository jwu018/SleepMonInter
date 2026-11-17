import { Suspense } from "react";
import { BlockSkeleton } from "@/components/Skeleton";
import { ServerUpload } from "@/components/upload/ServerUpload";
import { UploadWorkspace } from "@/components/upload/UploadWorkspace";
import { listPatients } from "@/lib/data";
import { serverUploadsEnabled } from "@/lib/data/serverUpload";

// Upload microSD recordings. Two ways, shown together:
//   1. Check in the browser (always): files are read in this tab only and never leave the
//      computer. Good for a quick look at a trial.
//   2. Save to the server (only when the site runs with the FastAPI backend): the file is
//      stored, validated and processed, and the night joins the patient's list.
export default function UploadPage() {
  return (
    <section className="space-y-6">
      <div className="print:hidden">
        <h1 className="text-2xl font-semibold tracking-tight">Upload recordings</h1>
        <p className="text-sm text-muted">
          Read recordings straight from the device&apos;s microSD card to check what was captured.
        </p>
      </div>

      <Suspense fallback={<BlockSkeleton height={240} />}>
        <Workspace />
      </Suspense>
    </section>
  );
}

async function Workspace() {
  // Study codes for the patient dropdowns (needs a signed-in user).
  const patients = await listPatients();
  const studyCodes = patients.map((p) => p.study_code);
  return (
    <>
      {serverUploadsEnabled() && <ServerUpload studyCodes={studyCodes} />}

      <div className="rounded-md border border-border bg-surface px-4 py-3 text-sm print:hidden">
        <strong>Check in this browser: stays on this computer.</strong> Files chosen below are read in
        this browser tab only. Nothing is uploaded to a server, and everything is cleared when you close
        or reload the tab. Recordings with sensor data are analysed for breaths, rate, pauses and signal
        quality; tick two or three to compare them.
      </div>

      <UploadWorkspace studyCodes={studyCodes} />
    </>
  );
}
