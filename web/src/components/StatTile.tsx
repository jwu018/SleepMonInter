import type { ReactNode } from "react";

/** A labeled headline number, e.g. "Median RR · 19.5 bpm". */
export function StatTile({ label, value, unit, note }: { label: string; value: ReactNode; unit?: string; note?: ReactNode }) {
  return (
    <div className="rounded-lg border border-border bg-surface p-4">
      <p className="text-sm text-muted">{label}</p>
      <p className="mt-1 text-2xl font-semibold">
        {value}
        {unit && <span className="ml-1 text-sm font-normal text-muted">{unit}</span>}
      </p>
      {note && <p className="mt-1 text-xs text-muted">{note}</p>}
    </div>
  );
}
