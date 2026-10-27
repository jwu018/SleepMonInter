// Main-thread side of the worker: start a worker for one file and wrap its messages in a
// Promise, with a progress callback.

import type { DeviceRecording } from "./parseDeviceCsv";
import type { WorkerResponse } from "./parse.worker";

export function readRecording(
  file: File,
  onProgress: (fraction: number) => void,
): Promise<{ hash: string; recording: DeviceRecording }> {
  return new Promise((resolve, reject) => {
    // This exact `new Worker(new URL(...), import.meta.url)` shape is what lets Next.js
    // find and bundle the worker file.
    const worker = new Worker(new URL("./parse.worker.ts", import.meta.url), { type: "module" });
    worker.onmessage = (event: MessageEvent<WorkerResponse>) => {
      const msg = event.data;
      if (msg.type === "progress") {
        onProgress(msg.fraction);
        return;
      }
      worker.terminate();
      if (msg.type === "done") resolve({ hash: msg.hash, recording: msg.recording });
      else reject(new Error(msg.message));
    };
    worker.onerror = (event) => {
      worker.terminate();
      reject(new Error(event.message || "The file reader stopped unexpectedly."));
    };
    worker.postMessage({ file });
  });
}
