// Shown on every page via the root layout, so no screen can be mistaken for real patient data.
// `sticky top-0` keeps it visible while scrolling long night views.
export function PrototypeBanner() {
  return (
    <div
      role="note"
      className="sticky top-0 z-50 bg-banner px-4 py-1.5 text-center text-sm font-medium text-banner-foreground"
    >
      Prototype — synthetic data only. Not for clinical use.
    </div>
  );
}
