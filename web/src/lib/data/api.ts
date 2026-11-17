import "server-only";

import type { MinuteMetrics, Patient, PatientSummary, RecordingDetail, WaveformWindow } from "./types";

// The FastAPI data source (api/). Used instead of the bundled files when DATA_SOURCE=api.
//
// These functions run only on the Next.js server. The browser never calls the API itself:
// it asks Next.js, Next.js checks the login session, and then Next.js calls the API with a
// shared secret (API_SHARED_SECRET). So the secret and the API address never reach the
// browser, and neither variable may get a NEXT_PUBLIC_ prefix.
//
// index.ts has already checked the session and validated the IDs before calling these.

const TIMEOUT_MS = 10_000;

/** GET a path from the API. Returns null for 404 (unknown patient or recording). */
async function apiGet<T>(path: string): Promise<T | null> {
  const base = process.env.API_URL;
  if (!base) throw new Error("DATA_SOURCE=api but API_URL is not set (see .env.example)");
  const headers: Record<string, string> = { Accept: "application/json" };
  if (process.env.API_SHARED_SECRET) headers["X-API-Key"] = process.env.API_SHARED_SECRET;

  const response = await fetch(new URL(path, base), {
    headers,
    // Always ask the API: recordings can change (uploads, reprocessing).
    cache: "no-store",
    // Give up instead of hanging the page if the API is down.
    signal: AbortSignal.timeout(TIMEOUT_MS),
  });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`API ${path} answered ${response.status}`);
  return (await response.json()) as T;
}

export async function listPatients(): Promise<PatientSummary[]> {
  return (await apiGet<PatientSummary[]>("/patients")) ?? [];
}

export function getPatient(studyCode: string): Promise<Patient | null> {
  return apiGet<Patient>(`/patients/${studyCode}`);
}

export async function getRecording(recordingId: string): Promise<RecordingDetail | null> {
  // Two requests at once: the night's metadata + summary, and its per-minute metrics.
  const [meta, metrics] = await Promise.all([
    apiGet<Omit<RecordingDetail, "metrics">>(`/recordings/${recordingId}`),
    apiGet<MinuteMetrics>(`/recordings/${recordingId}/metrics`),
  ]);
  return meta && metrics ? { ...meta, metrics } : null;
}

export function getWaveform(
  recordingId: string,
  startMs: number,
  endMs: number,
  maxPoints: number,
): Promise<WaveformWindow | null> {
  const query = new URLSearchParams({
    start_ms: String(Math.max(0, startMs)),
    end_ms: String(Math.max(0, endMs)),
    // The API accepts 10 to 10,000 points.
    max_points: String(Math.min(10_000, Math.max(10, Math.round(maxPoints)))),
  });
  return apiGet<WaveformWindow>(`/recordings/${recordingId}/waveform?${query}`);
}
