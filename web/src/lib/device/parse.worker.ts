// Web Worker: reads one recording file off the main thread, so the page stays responsive
// even for a ~60 MB overnight file. It fingerprints the file (to spot duplicates), then
// decodes and parses it in 1 MB chunks, reporting progress as it goes.
//
// The file is only read here, in the user's browser. Nothing is sent to a server.

import { analyzeRecording, type BreathingAnalysis } from "../processing/breathing";
import { createDeviceParser, type DeviceRecording } from "./parseDeviceCsv";

export type WorkerRequest = { file: File };
export type WorkerResponse =
  | { type: "progress"; fraction: number }
  | {
      type: "done";
      hash: string;
      recording: DeviceRecording;
      analysis: BreathingAnalysis | null;
      analysis_error: string | null;
    }
  | { type: "error"; message: string };

const CHUNK_BYTES = 1024 * 1024;

// TypeScript here is configured for normal pages (the "dom" library), which types
// `self.postMessage` like a window's. This narrow type describes the worker version.
const worker = self as unknown as {
  postMessage(message: WorkerResponse, transfer?: Transferable[]): void;
  onmessage: ((event: MessageEvent<WorkerRequest>) => void) | null;
};

worker.onmessage = async (event) => {
  try {
    const bytes = new Uint8Array(await event.data.file.arrayBuffer());

    // SHA-256 of the contents: the same file picked twice (even renamed) gets the same hash.
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    const hash = Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");

    const parser = createDeviceParser();
    // stream: true makes TextDecoder hold back a multi-byte character split across chunks.
    const decoder = new TextDecoder("utf-8");
    for (let offset = 0; offset < bytes.length; offset += CHUNK_BYTES) {
      parser.push(decoder.decode(bytes.subarray(offset, offset + CHUNK_BYTES), { stream: true }));
      worker.postMessage({ type: "progress", fraction: Math.min(1, (offset + CHUNK_BYTES) / bytes.length) });
    }
    parser.push(decoder.decode());
    const recording = parser.finish();

    // Breathing analysis (band-pass, breath detection...). A failure here shouldn't hide the
    // file itself, so it's reported separately.
    let analysis: BreathingAnalysis | null = null;
    let analysisError: string | null = null;
    try {
      analysis = analyzeRecording(recording);
    } catch (err) {
      analysisError = `Breathing analysis failed: ${err instanceof Error ? err.message : String(err)}`;
    }

    // "Transfer" the big arrays instead of copying them: ownership moves to the page instantly.
    const c = recording.columns;
    // bands.breathing IS `filtered` (same buffer), so it's listed once.
    const transfer = analysis
      ? [analysis.filtered.buffer, analysis.bands.noise.buffer, analysis.bands.interference.buffer]
      : [];
    worker.postMessage({ type: "done", hash, recording, analysis, analysis_error: analysisError }, [
      ...transfer,
      c.elapsed_ms.buffer,
      c.sample.buffer,
      c.ldc_L_uH.buffer,
      c.ldc_freq_hz.buffer,
      c.ldc_flags.buffer,
      c.a0_raw.buffer,
      c.vbat_v.buffer,
      c.battery_pct.buffer,
    ]);
  } catch (err) {
    worker.postMessage({ type: "error", message: err instanceof Error ? err.message : String(err) });
  }
};
