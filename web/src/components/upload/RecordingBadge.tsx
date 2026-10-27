import type { RecordingBadge as Badge } from "@/lib/device/parseDeviceCsv";

// Status badge for an uploaded recording. Color is never the only signal: every badge
// has an icon and a text label.
const BADGES: Record<Badge, { icon: string; label: string; className: string }> = {
  clean: { icon: "✓", label: "Clean", className: "border-status-good/60 bg-status-good/10" },
  check: { icon: "!", label: "Check data", className: "border-status-warning/60 bg-status-warning/10" },
  ended_unexpectedly: {
    icon: "⚠",
    label: "Ended unexpectedly",
    className: "border-status-serious/60 bg-status-serious/10",
  },
  no_sensor: { icon: "∅", label: "No sensor data", className: "border-status-neutral/60 bg-status-neutral/10" },
};

export function RecordingBadge({ badge }: { badge: Badge }) {
  const b = BADGES[badge];
  return (
    <span className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-xs ${b.className}`}>
      <span aria-hidden>{b.icon}</span>
      {b.label}
    </span>
  );
}
