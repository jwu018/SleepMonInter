// Upload page shell. The real upload (validate, store, process) arrives with the backend.
// Everything is visibly disabled, so nobody mistakes it for a working feature.
export default function UploadPage() {
  return (
    <section className="max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Upload a night</h1>
        <p className="text-sm text-muted">
          Caregivers will upload the night&apos;s file from the device&apos;s SD card here.
        </p>
      </div>

      <div className="rounded-md border border-status-warning/60 bg-status-warning/10 px-4 py-3 text-sm">
        <strong>Coming soon.</strong> Uploading needs the backend, which is planned for a later
        phase. This page shows the intended layout only.
      </div>

      <form className="space-y-4 opacity-60">
        <fieldset disabled className="space-y-4">
          <label className="block space-y-1">
            <span className="text-sm font-medium">Patient</span>
            <select className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm">
              <option>Select a study code…</option>
            </select>
          </label>
          <div className="grid place-items-center rounded-lg border-2 border-dashed border-border px-6 py-12 text-center">
            <p className="font-medium">Drag and drop a recording file</p>
            <p className="text-sm text-muted">.csv from the SD card, up to 50 MB</p>
          </div>
          <button
            type="submit"
            className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-background"
          >
            Upload and process
          </button>
        </fieldset>
      </form>
    </section>
  );
}
