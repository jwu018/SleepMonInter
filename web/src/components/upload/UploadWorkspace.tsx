"use client";

import { useRef, useState } from "react";
import { fromDataTransfer, fromFileList, type PickedFile } from "@/lib/device/collectFiles";
import { describeIssues, isRecordingFile, type DeviceRecording } from "@/lib/device/parseDeviceCsv";
import { readRecording } from "@/lib/device/readRecording";
import { formatElapsed } from "@/lib/device/trace";
import { RecordingBadge } from "./RecordingBadge";
import { UploadedRecordingView } from "./UploadedRecordingView";

// The upload page's interactive part. Files are read in this browser tab only:
// everything lives in React state (memory), so closing or reloading the tab clears it.
// Nothing is sent to the server.

interface Item {
  id: string;
  name: string;
  path: string;
  sizeBytes: number;
  status: "reading" | "ready" | "duplicate" | "error";
  progress: number;
  message?: string;
  recording?: DeviceRecording;
  studyCode: string;
}

const MAX_FILE_BYTES = 150 * 1024 * 1024; // an overnight file is ~60 MB

export function UploadWorkspace({ studyCodes }: { studyCodes: string[] }) {
  const [items, setItems] = useState<Item[]>([]);
  const [ignored, setIgnored] = useState<string[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  // Content fingerprints already imported -> file name, to catch duplicates (even renamed).
  const hashes = useRef(new Map<string, string>());
  const nextId = useRef(0);

  const update = (id: string, patch: Partial<Item>) =>
    setItems((cur) => cur.map((it) => (it.id === id ? { ...it, ...patch } : it)));

  async function importFiles(picked: PickedFile[]) {
    const recordings = picked.filter((p) => isRecordingFile(p.path));
    setIgnored((cur) => [...cur, ...picked.filter((p) => !isRecordingFile(p.path)).map((p) => p.path)]);
    if (recordings.length === 0) return;

    const queued: Item[] = recordings
      .sort((a, b) => a.path.localeCompare(b.path))
      .map((p) => ({
        id: String(nextId.current++),
        name: p.file.name,
        path: p.path,
        sizeBytes: p.file.size,
        status: "reading",
        progress: 0,
        studyCode: "",
      }));
    setItems((cur) => [...cur, ...queued]);
    setBusy(true);

    // One file at a time: keeps memory use predictable for big overnight files.
    for (const [i, item] of queued.entries()) {
      const file = recordings[i].file;
      if (file.size > MAX_FILE_BYTES) {
        update(item.id, { status: "error", message: "File is larger than 150 MB." });
        continue;
      }
      try {
        const { hash, recording } = await readRecording(file, (f) => update(item.id, { progress: f }));
        const existing = hashes.current.get(hash);
        if (existing) {
          update(item.id, { status: "duplicate", progress: 1, message: `Same contents as ${existing}; not imported twice.` });
        } else {
          hashes.current.set(hash, item.name);
          update(item.id, { status: "ready", progress: 1, recording });
        }
      } catch (err) {
        update(item.id, { status: "error", message: err instanceof Error ? err.message : String(err) });
      }
    }
    setBusy(false);
  }

  function clearAll() {
    setItems([]);
    setIgnored([]);
    setSelectedId(null);
    hashes.current.clear();
  }

  const selected = items.find((it) => it.id === selectedId && it.recording);
  if (selected?.recording) {
    return (
      <UploadedRecordingView
        key={selected.id}
        name={selected.name}
        recording={selected.recording}
        studyCode={selected.studyCode}
        onBack={() => setSelectedId(null)}
      />
    );
  }

  return (
    <div className="space-y-6">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={async (e) => {
          e.preventDefault();
          setDragging(false);
          await importFiles(await fromDataTransfer(e.dataTransfer));
        }}
        className={`grid place-items-center gap-3 rounded-lg border-2 border-dashed px-6 py-10 text-center ${
          dragging ? "border-accent bg-accent/10" : "border-border"
        }`}
      >
        <p className="font-medium">Drag the microSD card&apos;s folder or files here</p>
        <p className="text-sm text-muted">
          Recordings named like <code>S20261026_205511.csv</code> are picked up automatically; other files are ignored.
        </p>
        <div className="flex flex-wrap justify-center gap-2">
          <label className="cursor-pointer rounded-md bg-accent px-4 py-2 text-sm font-medium text-background">
            Choose SD card folder
            {/* webkitdirectory isn't in React's types, so it's passed through a plain object. */}
            <input
              type="file"
              multiple
              className="sr-only"
              {...{ webkitdirectory: "" }}
              onChange={(e) => {
                void importFiles(fromFileList(e.target.files));
                e.target.value = ""; // allow picking the same folder again
              }}
            />
          </label>
          <label className="cursor-pointer rounded-md border border-border px-4 py-2 text-sm hover:bg-surface">
            Choose files
            <input
              type="file"
              multiple
              accept=".csv"
              className="sr-only"
              onChange={(e) => {
                void importFiles(fromFileList(e.target.files));
                e.target.value = "";
              }}
            />
          </label>
        </div>
      </div>

      {items.length > 0 && (
        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold">Recordings in this tab ({items.length})</h2>
            <button
              type="button"
              onClick={clearAll}
              disabled={busy}
              className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-surface disabled:opacity-40"
            >
              Clear all
            </button>
          </div>
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full text-left text-sm">
              <thead className="bg-surface text-muted">
                <tr>
                  <th className="px-3 py-2 font-medium">File</th>
                  <th className="px-3 py-2 font-medium">Device clock at start</th>
                  <th className="px-3 py-2 text-right font-medium">Duration</th>
                  <th className="px-3 py-2 text-right font-medium">Rows</th>
                  <th className="px-3 py-2 font-medium">Sensor</th>
                  <th className="px-3 py-2 text-right font-medium">Missed</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2 font-medium">Patient</th>
                </tr>
              </thead>
              <tbody>
                {items.map((it) => (
                  <ItemRow
                    key={it.id}
                    item={it}
                    studyCodes={studyCodes}
                    onOpen={() => setSelectedId(it.id)}
                    onTag={(code) => update(it.id, { studyCode: code })}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {ignored.length > 0 && (
        <details className="text-sm text-muted">
          <summary className="cursor-pointer">{ignored.length} other file(s) ignored (not recordings)</summary>
          <ul className="mt-2 list-inside list-disc">
            {ignored.slice(0, 50).map((p, i) => (
              <li key={`${p}-${i}`}>{p}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function ItemRow({
  item,
  studyCodes,
  onOpen,
  onTag,
}: {
  item: Item;
  studyCodes: string[];
  onOpen: () => void;
  onTag: (code: string) => void;
}) {
  const rec = item.recording;
  if (!rec) {
    return (
      <tr className="border-t border-border">
        <td className="px-3 py-2 font-medium">{item.name}</td>
        <td colSpan={7} className="px-3 py-2">
          {item.status === "reading" ? (
            <div className="flex items-center gap-3">
              <div
                className="h-2 w-48 overflow-hidden rounded-full bg-accent/20"
                role="progressbar"
                aria-valuenow={Math.round(item.progress * 100)}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-label={`Reading ${item.name}`}
              >
                <div className="h-full bg-accent" style={{ width: `${item.progress * 100}%` }} />
              </div>
              <span className="text-xs text-muted">Reading… {Math.round(item.progress * 100)}%</span>
            </div>
          ) : (
            <span className="text-muted">{item.message}</span>
          )}
        </td>
      </tr>
    );
  }

  const issues = describeIssues(rec);
  return (
    <tr className="border-t border-border hover:bg-surface">
      <td className="px-3 py-2 font-medium">
        <button type="button" onClick={onOpen} className="text-accent hover:underline">
          {item.name}
        </button>
      </td>
      <td className="px-3 py-2">{rec.meta.start_local ?? "—"}</td>
      <td className="tabular px-3 py-2 text-right">{formatElapsed(rec.stats.duration_ms / 1000)}</td>
      <td className="tabular px-3 py-2 text-right">{rec.stats.row_count.toLocaleString()}</td>
      <td className="px-3 py-2">{rec.stats.sensor_rows > 0 ? "Yes" : "No"}</td>
      <td className="tabular px-3 py-2 text-right">{rec.stats.missed_samples}</td>
      <td className="px-3 py-2">
        <RecordingBadge badge={issues.badge} />
      </td>
      <td className="px-3 py-2">
        <select
          value={item.studyCode}
          onChange={(e) => onTag(e.target.value)}
          aria-label={`Patient for ${item.name}`}
          className="rounded-md border border-border bg-background px-2 py-1 text-sm"
        >
          <option value="">Untagged</option>
          {studyCodes.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </td>
    </tr>
  );
}
