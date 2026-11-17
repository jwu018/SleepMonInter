"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

// Save one recording to the server: pick a patient and a file, send it, then watch the
// processing status until the night is ready to open. Shown only when the site runs with
// the FastAPI backend (DATA_SOURCE=api).

interface Report {
  ok: boolean;
  errors: string[];
  warnings: string[];
  rows: number;
  duration_s: number;
  gap_count: number;
}

type State =
  | { step: "idle" }
  | { step: "sending" }
  | { step: "rejected"; message: string; report: Report | null; canReplace: boolean }
  | { step: "tracking"; recordingId: string; status: string; error: string | null; report: Report };

const POLL_MS = 2000;
const STATUS_TEXT: Record<string, string> = {
  uploaded: "Saved. Waiting to be processed…",
  processing: "Processing: finding breaths and computing per-minute rate…",
  processed: "Processed.",
  failed: "Processing failed.",
};

function formatDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  return h > 0 ? `${h} h ${m} min` : `${m} min`;
}

export function ServerUpload({ studyCodes }: { studyCodes: string[] }) {
  const [studyCode, setStudyCode] = useState(studyCodes[0] ?? "");
  const [file, setFile] = useState<File | null>(null);
  // The device clock has no time zone. Assume it was set to this computer's zone.
  const [offsetHours, setOffsetHours] = useState(() => -new Date().getTimezoneOffset() / 60);
  const [state, setState] = useState<State>({ step: "idle" });
  const fileInput = useRef<HTMLInputElement>(null);

  const trackingId = state.step === "tracking" ? state.recordingId : null;
  const finished = state.step === "tracking" && (state.status === "processed" || state.status === "failed");

  // While a recording is being processed, ask for its status every two seconds.
  useEffect(() => {
    if (!trackingId || finished) return;
    const timer = setInterval(async () => {
      try {
        const response = await fetch(`/api/recordings/${trackingId}/status`);
        if (!response.ok) return; // try again on the next tick
        const body = (await response.json()) as { status: string; error_message: string | null };
        setState((s) => (s.step === "tracking" ? { ...s, status: body.status, error: body.error_message } : s));
      } catch {
        // Network hiccup: keep polling.
      }
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [trackingId, finished]);

  async function send(replace: boolean) {
    if (!file || !studyCode) return;
    setState({ step: "sending" });
    const form = new FormData();
    form.set("file", file);
    form.set("study_code", studyCode);
    form.set("utc_offset_hours", String(offsetHours));
    form.set("replace", String(replace));
    try {
      const response = await fetch("/api/uploads", { method: "POST", body: form });
      const body = await response.json();
      if (response.status === 201) {
        setState({ step: "tracking", recordingId: body.recording_id, status: body.status, error: null, report: body.report });
      } else if (response.status === 422 && body.detail?.errors) {
        setState({ step: "rejected", message: "This file can't be used.", report: body.detail, canReplace: false });
      } else {
        const message = typeof body.detail === "string" ? body.detail : "The upload failed.";
        setState({ step: "rejected", message, report: null, canReplace: response.status === 409 });
      }
    } catch {
      setState({ step: "rejected", message: "The upload failed. Check the connection and try again.", report: null, canReplace: false });
    }
  }

  const busy = state.step === "sending" || (state.step === "tracking" && !finished);
  const report = state.step === "tracking" || state.step === "rejected" ? state.report : null;

  return (
    <div className="space-y-4 rounded-md border border-border p-4 print:hidden">
      <div>
        <h2 className="text-lg font-semibold">Save a recording to the server</h2>
        <p className="text-sm text-muted">
          The file is stored, checked and analysed, then appears in the patient&apos;s list of nights.
          Use test or synthetic recordings only.
        </p>
      </div>

      <div className="flex flex-wrap items-end gap-4 text-sm">
        <label className="space-y-1">
          <span className="block text-muted">Patient</span>
          <select
            value={studyCode}
            onChange={(e) => setStudyCode(e.target.value)}
            disabled={busy}
            className="rounded-md border border-border bg-background px-2 py-1.5"
          >
            {studyCodes.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
        <label className="space-y-1">
          <span className="block text-muted">Recording file (S….csv)</span>
          <input
            ref={fileInput}
            type="file"
            accept=".csv,text/csv"
            disabled={busy}
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null);
              setState({ step: "idle" });
            }}
            className="block text-sm"
          />
        </label>
        <label className="space-y-1">
          <span className="block text-muted">Device clock, hours from UTC</span>
          <input
            type="number"
            step={0.5}
            min={-12}
            max={14}
            value={offsetHours}
            disabled={busy}
            onChange={(e) => setOffsetHours(Number(e.target.value))}
            className="w-24 rounded-md border border-border bg-background px-2 py-1.5"
          />
        </label>
        <button
          type="button"
          onClick={() => send(false)}
          disabled={!file || !studyCode || busy}
          className="rounded-md bg-foreground px-4 py-1.5 font-medium text-background disabled:opacity-40"
        >
          {state.step === "sending" ? "Uploading…" : "Upload"}
        </button>
      </div>

      {state.step === "rejected" && (
        <div role="alert" className="space-y-2 text-sm">
          <p className="font-medium text-red-600 dark:text-red-400">{state.message}</p>
          {state.canReplace && (
            <button
              type="button"
              onClick={() => send(true)}
              className="rounded-md border border-border px-3 py-1.5 hover:bg-surface"
            >
              Replace the existing recording
            </button>
          )}
        </div>
      )}

      {state.step === "tracking" && (
        <div role="status" className="space-y-1 text-sm">
          <p className="font-medium">
            {state.recordingId}: {STATUS_TEXT[state.status] ?? state.status}
          </p>
          {state.status === "failed" && state.error && <p className="text-muted">Reason: {state.error}</p>}
          {state.status === "processed" && (
            <Link href={`/recordings/${state.recordingId}`} className="underline">
              Open this night
            </Link>
          )}
        </div>
      )}

      {report && (
        <div className="space-y-1 text-sm">
          {report.rows > 0 && (
            <p className="text-muted">
              {report.rows.toLocaleString()} samples, {formatDuration(report.duration_s)}, {report.gap_count} data
              gap{report.gap_count === 1 ? "" : "s"} longer than 1 s
            </p>
          )}
          {report.errors.length > 0 && (
            <ul className="list-inside list-disc">
              {report.errors.map((e) => (
                <li key={e}>{e}</li>
              ))}
            </ul>
          )}
          {report.warnings.length > 0 && (
            <ul className="list-inside list-disc text-muted">
              {report.warnings.map((w) => (
                <li key={w}>Note: {w}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
