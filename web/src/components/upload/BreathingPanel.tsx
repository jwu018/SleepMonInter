"use client";

import { useState } from "react";
import { StatTile } from "@/components/StatTile";
import { formatElapsed } from "@/lib/device/trace";
import {
  type BreathingAnalysis,
  countCompleteBreaths,
  GOOD_SIR_DB,
  GOOD_SNR_DB,
  PAUSE_S,
  snrSirDb,
} from "@/lib/processing/breathing";

// Breathing results for an uploaded recording, for Test 2:
// - complete breaths and breaths/min inside the counting window (trims skip the belt settling);
// - a readout for any stretch dragged on the chart;
// - pauses longer than 10 s (descriptive review markers, not a diagnosis).

export function BreathingPanel({
  analysis,
  error,
  selection,
  onClearSelection,
}: {
  analysis: BreathingAnalysis | null;
  error: string | null;
  selection: [number, number] | null;
  onClearSelection: () => void;
}) {
  const [trimStart, setTrimStart] = useState(10);
  const [trimEnd, setTrimEnd] = useState(5);

  if (!analysis) {
    return (
      <p className="rounded-md border border-status-neutral/60 bg-status-neutral/10 px-3 py-2 text-sm">
        {error ?? "No breathing analysis: this recording has no sensor data."}
      </p>
    );
  }

  const fs = analysis.fs_hz;
  const durationS = analysis.n_samples / fs;
  const start = Math.max(0, trimStart);
  const end = Math.max(start, durationS - Math.max(0, trimEnd));
  const count = countCompleteBreaths(analysis.breaths, fs, start, end);
  const windowMin = (end - start) / 60;
  const [snr, sir] = snrSirDb(analysis.bands, Math.trunc(start * fs), Math.trunc(end * fs), fs);
  const fmtDb = (v: number) => (Number.isFinite(v) ? v.toFixed(1) : "—");
  const lowQuality = snr < GOOD_SNR_DB || sir < GOOD_SIR_DB;

  const selCount = selection ? countCompleteBreaths(analysis.breaths, fs, selection[0], selection[1]) : 0;
  const selMin = selection ? (selection[1] - selection[0]) / 60 : 0;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-4 text-sm">
        <label className="space-y-1">
          <span className="block text-muted">Skip after switch-on (s)</span>
          <input
            type="number"
            min={0}
            step={1}
            value={trimStart}
            onChange={(e) => setTrimStart(Number(e.target.value))}
            className="w-24 rounded-md border border-border bg-background px-2 py-1"
          />
        </label>
        <label className="space-y-1">
          <span className="block text-muted">Skip before switch-off (s)</span>
          <input
            type="number"
            min={0}
            step={1}
            value={trimEnd}
            onChange={(e) => setTrimEnd(Number(e.target.value))}
            className="w-24 rounded-md border border-border bg-background px-2 py-1"
          />
        </label>
        <p className="max-w-md text-xs text-muted">
          Counters must count the same window: from {formatElapsed(start)} to {formatElapsed(end)} after
          switch-on. Skipping the start avoids counting the belt settling as breaths.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatTile label="Complete breaths" value={count} note={`in ${formatElapsed(end - start)} counted`} />
        <StatTile
          label="Breathing rate"
          value={windowMin > 0 ? (count / windowMin).toFixed(1) : "—"}
          unit="/min"
        />
        <StatTile
          label={`Pauses > ${PAUSE_S} s`}
          value={analysis.pauses.length}
          note="Review markers, not a diagnosis"
        />
        <StatTile
          label="Readings removed"
          value={`${Math.round(analysis.removed_fraction * 100)}%`}
          note={analysis.removed_fraction > 0.2 ? "⚠ sensor unreliable for this trial" : "stuck, out of range or spikes"}
        />
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatTile
          label="Signal-to-noise (SNR)"
          value={fmtDb(snr)}
          unit="dB"
          note={`breathing vs >1 Hz sensor noise; good ≥ ${GOOD_SNR_DB} dB`}
        />
        <StatTile
          label="Signal-to-interference (SIR)"
          value={fmtDb(sir)}
          unit="dB"
          note={`breathing vs <0.1 Hz drift/movement; good ≥ ${GOOD_SIR_DB} dB`}
        />
        <div className="col-span-2 self-center text-xs text-muted">
          {lowQuality
            ? "⚠ Signal quality is below target for this window: check the belt fit before trusting the count."
            : "Signal quality is good for this window."}{" "}
          Movement at breathing speed can&apos;t be seen by either ratio. Thresholds are starting
          values, to be tuned on the Test 2 recordings.
        </div>
      </div>

      <div className="rounded-md border border-border p-3 text-sm">
        {selection ? (
          <div className="flex flex-wrap items-center gap-3">
            <span>
              Selected {formatElapsed(selection[0])}–{formatElapsed(selection[1])}:{" "}
              <strong>{selCount} complete breaths</strong>
              {selMin > 0 && <> = {(selCount / selMin).toFixed(1)} /min</>}
              {(() => {
                const [sSnr, sSir] = snrSirDb(analysis.bands, Math.trunc(selection[0] * fs), Math.trunc(selection[1] * fs), fs);
                return (
                  <span className="text-muted">
                    {" "}
                    · SNR {fmtDb(sSnr)} dB · SIR {fmtDb(sSir)} dB
                  </span>
                );
              })()}
            </span>
            <button type="button" onClick={onClearSelection} className="text-accent hover:underline">
              Clear
            </button>
          </div>
        ) : (
          <span className="text-muted">Drag across the chart below to count breaths in any stretch.</span>
        )}
      </div>

      {analysis.pauses.length > 0 && (
        <ul className="list-inside list-disc text-sm">
          {analysis.pauses.map(([a, b]) => (
            <li key={a}>
              Breathing pause &gt; {PAUSE_S} s: {formatElapsed(a)}–{formatElapsed(b)} ({(b - a).toFixed(1)} s)
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
