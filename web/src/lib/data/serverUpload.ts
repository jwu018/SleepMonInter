import "server-only";

// Server-side upload: forwards a device file to the FastAPI backend, which stores it,
// validates it and processes it. Only available when the dashboard reads from the API
// (DATA_SOURCE=api). The route handlers in app/api/ check the login session before calling
// these, and the shared secret is added here, on the server, so it never reaches the browser.

export const STUDY_CODE = /^NN-\d{3}$/;
export const RECORDING_ID = /^NN-\d{3}_\d{4}-\d{2}-\d{2}$/;

export function serverUploadsEnabled(): boolean {
  return process.env.DATA_SOURCE === "api" && Boolean(process.env.API_URL);
}

function apiHeaders(): Record<string, string> {
  return process.env.API_SHARED_SECRET ? { "X-API-Key": process.env.API_SHARED_SECRET } : {};
}

/** POST the form (file, study_code, utc_offset_hours, replace) to the API. */
export async function forwardUpload(form: FormData): Promise<Response> {
  // No timeout shorter than a big upload: a 60 MB night takes a while on a slow link.
  return fetch(new URL("/recordings/upload", process.env.API_URL), {
    method: "POST",
    headers: apiHeaders(),
    body: form,
    signal: AbortSignal.timeout(5 * 60_000),
  });
}

export interface RecordingStatus {
  recording_id: string;
  status: "uploaded" | "processing" | "processed" | "failed";
  error_message: string | null;
}

export async function fetchRecordingStatus(recordingId: string): Promise<RecordingStatus | null> {
  const response = await fetch(new URL(`/recordings/${recordingId}`, process.env.API_URL), {
    headers: apiHeaders(),
    cache: "no-store",
    signal: AbortSignal.timeout(10_000),
  });
  if (!response.ok) return null;
  const rec = (await response.json()) as RecordingStatus;
  return { recording_id: rec.recording_id, status: rec.status, error_message: rec.error_message ?? null };
}
