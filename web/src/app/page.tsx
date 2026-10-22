// Placeholder home page. In Phase 2 this becomes the patient list (behind login).
export default function Home() {
  return (
    <section className="max-w-2xl space-y-4">
      <h1 className="text-2xl font-semibold tracking-tight">
        Overnight respiratory monitoring
      </h1>
      <p className="text-muted">
        Night Night is a chest-worn RIP band that records breathing movement
        overnight for children with neuromuscular disorders. This dashboard will
        show respiratory rate and relative breathing amplitude across nights.
      </p>
      <div className="rounded-lg border border-border bg-surface p-4 text-sm">
        <p className="font-medium">Coming in Phase 2</p>
        <p className="mt-1 text-muted">
          Sign in, patient list, night view with trend charts, waveform zoom,
          compare nights, and print report.
        </p>
      </div>
    </section>
  );
}
