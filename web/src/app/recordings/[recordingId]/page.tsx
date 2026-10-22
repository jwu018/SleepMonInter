import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { BatteryPanel } from "@/components/BatteryPanel";
import { NightCharts } from "@/components/charts/NightCharts";
import { LocalTime } from "@/components/LocalTime";
import { BlockSkeleton } from "@/components/Skeleton";
import { StatTile } from "@/components/StatTile";
import { getRecording } from "@/lib/data";
import { formatDuration, formatNumber } from "@/lib/format";

// Night view: summary numbers, trend charts with quality shading, raw waveform, battery.
export default function RecordingPage({ params }: PageProps<"/recordings/[recordingId]">) {
  return (
    <Suspense fallback={<BlockSkeleton height={600} />}>
      <NightView params={params} />
    </Suspense>
  );
}

async function NightView({ params }: { params: PageProps<"/recordings/[recordingId]">["params"] }) {
  const { recordingId } = await params;
  const rec = await getRecording(recordingId);
  if (!rec) notFound();

  const durationMs = rec.metrics.minute_index.length * 60_000;

  return (
    <article className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm text-muted">
            <Link href="/" className="hover:underline">
              Patients
            </Link>{" "}
            /{" "}
            <Link href={`/patients/${rec.study_code}`} className="hover:underline">
              {rec.study_code}
            </Link>{" "}
            / Night
          </p>
          <h1 className="text-2xl font-semibold tracking-tight">
            Night of <LocalTime iso={rec.start_utc} format="date" />
          </h1>
          <p className="text-sm text-muted">
            <LocalTime iso={rec.start_utc} format="time" /> – <LocalTime iso={rec.end_utc} format="time" /> ·{" "}
            {formatDuration(rec.duration_min)} · device {rec.device_id}
          </p>
        </div>
        <Link
          href={`/recordings/${rec.recording_id}/report`}
          className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-surface"
        >
          Print report
        </Link>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatTile label="Median respiratory rate" value={formatNumber(rec.median_resp_rate_bpm)} unit="bpm" />
        <StatTile
          label="Mean relative amplitude"
          value={formatNumber(rec.mean_amplitude_rel, 2)}
          unit="×"
          note="1.0 = this night's median breath"
        />
        <StatTile
          label="Good signal"
          value={formatNumber(rec.pct_good, 0)}
          unit="%"
          note={`${formatNumber(rec.pct_poor, 0)}% poor · ${formatNumber(rec.pct_no_signal, 0)}% no signal`}
        />
        <StatTile label="Data gaps" value={rec.gap_count} note="Breaks of more than 1 s in the file" />
      </div>

      <div className="grid gap-8 lg:grid-cols-[1fr_280px]">
        <NightCharts
          recordingId={rec.recording_id}
          startUtc={rec.start_utc}
          durationMs={durationMs}
          metrics={rec.metrics}
        />
        <aside>
          <BatteryPanel startMv={rec.battery_start_mv} endMv={rec.battery_end_mv} durationMin={rec.duration_min} />
        </aside>
      </div>
    </article>
  );
}
