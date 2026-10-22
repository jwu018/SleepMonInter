import "server-only";

import { readFile } from "node:fs/promises";
import path from "node:path";
import { requireUser } from "@/lib/auth";
import type {
  Patient,
  PatientSummary,
  RecordingDetail,
  WaveformWindow,
} from "./types";

// The data-access layer: the ONLY place the app reads recording data.
// Today it reads static files from web/data/ (built by tools/build_static_data.py).
// In Phase 3 these functions will call the FastAPI backend instead; pages won't change.
//
// Two rules every function here follows:
//   1. Check the user first (requireUser) -- never return data to a logged-out visitor.
//   2. Validate IDs before building a file path, so a crafted URL like
//      /recordings/..%2F..%2Fsecret can't read files outside web/data/.

const DATA_DIR = path.join(process.cwd(), "data");
const STUDY_CODE = /^NN-\d{3}$/;
const RECORDING_ID = /^NN-\d{3}_\d{4}-\d{2}-\d{2}$/;

interface IndexFile {
  synthetic: boolean;
  patients: Patient[];
}

interface RecordingFile extends RecordingDetail {
  waveform: {
    sample_rate_hz: number;
    offset_counts: number;
    n_samples: number;
    missing_value: number;
  };
}

// The files never change while the server runs, so each is read once and kept in memory.
const cache = new Map<string, Promise<unknown>>();

function readCached<T>(relativePath: string, parse: (buf: Buffer) => T): Promise<T> {
  let entry = cache.get(relativePath) as Promise<T> | undefined;
  if (!entry) {
    entry = readFile(path.join(DATA_DIR, relativePath)).then(parse);
    // Don't cache failures (e.g. a missing file), so a later request can retry.
    entry.catch(() => cache.delete(relativePath));
    cache.set(relativePath, entry);
  }
  return entry;
}

const readJson = <T>(relativePath: string) =>
  readCached<T>(relativePath, (buf) => JSON.parse(buf.toString("utf-8")) as T);

async function readRecordingFile(recordingId: string): Promise<RecordingFile | null> {
  if (!RECORDING_ID.test(recordingId)) return null;
  try {
    return await readJson<RecordingFile>(`recordings/${recordingId}.json`);
  } catch {
    return null;
  }
}

export async function listPatients(): Promise<PatientSummary[]> {
  await requireUser();
  const index = await readJson<IndexFile>("index.json");
  // Strip the nested recordings: the list page only needs the summary fields.
  return index.patients.map(({ recordings: _recordings, ...summary }) => summary);
}

export async function getPatient(studyCode: string): Promise<Patient | null> {
  await requireUser();
  if (!STUDY_CODE.test(studyCode)) return null;
  const index = await readJson<IndexFile>("index.json");
  return index.patients.find((p) => p.study_code === studyCode) ?? null;
}

export async function getRecording(recordingId: string): Promise<RecordingDetail | null> {
  await requireUser();
  const file = await readRecordingFile(recordingId);
  if (!file) return null;
  const { waveform: _waveform, ...detail } = file;
  return detail;
}

/**
 * Raw signal for [startMs, endMs), reduced to at most ~maxPoints points.
 *
 * When the window holds more points than that, it's split into buckets and each bucket
 * contributes its min and max. Drawing those as a line keeps spikes and the breathing
 * envelope visible, which plain "take every Nth point" would lose.
 */
export async function getWaveform(
  recordingId: string,
  startMs: number,
  endMs: number,
  maxPoints: number,
): Promise<WaveformWindow | null> {
  await requireUser();
  const file = await readRecordingFile(recordingId);
  if (!file) return null;
  const meta = file.waveform;

  const samples = await readCached(`waveforms/${recordingId}.i16`, (buf) =>
    // Copy into a fresh, aligned buffer: Node may hand back a slice of a shared pool.
    new Int16Array(buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength)),
  );

  const msPerSample = 1000 / meta.sample_rate_hz;
  const first = Math.max(0, Math.floor(startMs / msPerSample));
  const last = Math.min(meta.n_samples, Math.ceil(endMs / msPerSample));
  const toCounts = (v: number) => (v === meta.missing_value ? null : v + meta.offset_counts);

  const t_ms: number[] = [];
  const raw_value: (number | null)[] = [];
  const count = Math.max(0, last - first);

  if (count <= maxPoints) {
    for (let i = first; i < last; i++) {
      t_ms.push(i * msPerSample);
      raw_value.push(toCounts(samples[i]));
    }
    return { start_ms: first * msPerSample, end_ms: last * msPerSample, t_ms, raw_value, resolution: "raw" };
  }

  const buckets = Math.max(1, Math.floor(maxPoints / 2));
  const perBucket = count / buckets;
  for (let b = 0; b < buckets; b++) {
    const from = first + Math.floor(b * perBucket);
    const to = first + Math.floor((b + 1) * perBucket);
    let min = Infinity;
    let max = -Infinity;
    for (let i = from; i < to; i++) {
      const v = samples[i];
      if (v === meta.missing_value) continue;
      if (v < min) min = v;
      if (v > max) max = v;
    }
    const t = from * msPerSample;
    if (min === Infinity) {
      // The whole bucket is a data gap: a null breaks the line on the chart.
      t_ms.push(t);
      raw_value.push(null);
    } else {
      t_ms.push(t, t + (perBucket * msPerSample) / 2);
      raw_value.push(min + meta.offset_counts, max + meta.offset_counts);
    }
  }
  return { start_ms: first * msPerSample, end_ms: last * msPerSample, t_ms, raw_value, resolution: "envelope" };
}
