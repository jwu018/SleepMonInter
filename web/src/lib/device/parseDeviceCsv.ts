// Parser for the real logger's CSV format (firmware 0.1 / 0.2). See docs/DEVICE_FORMAT.md.
//
// It's written to be fed in pieces (`push(text)`), because overnight files are ~60 MB and
// are read in chunks inside a Web Worker. A chunk can end in the middle of a line, so the
// unfinished tail is kept until the next chunk arrives.
//
// This module has no imports and uses only plain TypeScript, so it runs unchanged in the
// browser, in the worker, and under `node --test`.

export interface DeviceMeta {
  firmware: string | null;
  /** Device clock at start, as written ("YYYY-MM-DD HH:MM:SS"). Local time, no time zone. */
  start_local: string | null;
  rtc: string | null;
  sample_rate_hz: number | null;
  /** The `# ldc1612,...` line: sensor settings, or a NOT FOUND message. */
  sensor_status: string | null;
}

export interface DriftCheck {
  datetime: string;
  elapsed_ms: number | null;
  drift_ms: number | null;
}

export interface StopLine {
  datetime: string;
  reason: string | null;
  rows: number | null;
  missed_slots: number | null;
}

export interface DeviceStats {
  row_count: number;
  /** From the first to the last sample, plus one sample period. */
  duration_ms: number;
  first_datetime: string | null;
  last_datetime: string | null;
  /** Rows that have an inductance value. 0 means the sensor wasn't connected. */
  sensor_rows: number;
  /** Rows with any ldc_flags bit set. */
  flagged_rows: number;
  /** Samples lost, counted from jumps in the `sample` index. */
  missed_samples: number;
  /** Intervals noticeably longer than the sample period (> 1.25×). */
  late_samples: number;
  max_interval_ms: number;
  /** Lines that couldn't be read (wrong number of fields, missing numbers). */
  malformed_lines: number;
}

export interface DeviceColumns {
  elapsed_ms: Float64Array;
  sample: Float64Array;
  /** NaN where blank (sensor missing). */
  ldc_L_uH: Float64Array;
  ldc_freq_hz: Float64Array;
  ldc_flags: Float64Array;
  a0_raw: Float64Array;
}

export interface DeviceRecording {
  meta: DeviceMeta;
  stats: DeviceStats;
  drift_checks: DriftCheck[];
  /** null = no stop line: the file ended unexpectedly (e.g. power was cut). */
  stop: StopLine | null;
  columns: DeviceColumns;
}

type ColumnName = keyof DeviceColumns;
const DEFAULT_SAMPLE_RATE_HZ = 25;

/** A number array that grows as rows arrive, stored compactly as Float64. */
class Column {
  private data = new Float64Array(4096);
  length = 0;

  push(value: number) {
    if (this.length === this.data.length) {
      const bigger = new Float64Array(this.data.length * 2);
      bigger.set(this.data);
      this.data = bigger;
    }
    this.data[this.length++] = value;
  }

  /** A right-sized copy, so no unused capacity is kept or sent between threads. */
  toArray(): Float64Array {
    return this.data.slice(0, this.length);
  }
}

/** Blank -> NaN, otherwise a number (NaN if it isn't one). */
function toNumber(field: string | undefined): number {
  if (field === undefined) return NaN;
  const trimmed = field.trim();
  return trimmed === "" ? NaN : Number(trimmed);
}

/** "key=value" pairs after the datetime in drift_check / stop lines. */
function parseKeyValues(parts: string[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const part of parts) {
    const eq = part.indexOf("=");
    if (eq > 0) out[part.slice(0, eq).trim()] = part.slice(eq + 1).trim();
  }
  return out;
}

function optionalNumber(value: string | undefined): number | null {
  if (value === undefined) return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

export function createDeviceParser() {
  const meta: DeviceMeta = {
    firmware: null,
    start_local: null,
    rtc: null,
    sample_rate_hz: null,
    sensor_status: null,
  };
  const driftChecks: DriftCheck[] = [];
  let stop: StopLine | null = null;

  const columns: Record<ColumnName, Column> = {
    elapsed_ms: new Column(),
    sample: new Column(),
    ldc_L_uH: new Column(),
    ldc_freq_hz: new Column(),
    ldc_flags: new Column(),
    a0_raw: new Column(),
  };
  // Position of each column in a data row, learned from the header row.
  let fieldIndex: Record<string, number> | null = null;
  let fieldCount = 0;

  let pending = ""; // unfinished last line of the previous chunk
  let firstDatetime: string | null = null;
  let lastDatetime: string | null = null;
  let firstElapsed = NaN;
  let prevElapsed = NaN;
  let prevSample = NaN;
  let sensorRows = 0;
  let flaggedRows = 0;
  let missedSamples = 0;
  let lateSamples = 0;
  let maxInterval = 0;
  let malformed = 0;

  function handleComment(line: string) {
    const body = line.replace(/^#\s*/, "");
    const comma = body.indexOf(",");
    const key = (comma >= 0 ? body.slice(0, comma) : body).trim();
    const rest = comma >= 0 ? body.slice(comma + 1).trim() : "";

    if (key === "drift_check" || key === "stop") {
      const parts = rest.split(",");
      const kv = parseKeyValues(parts.slice(1));
      if (key === "drift_check") {
        driftChecks.push({
          datetime: parts[0].trim(),
          elapsed_ms: optionalNumber(kv.elapsed_ms),
          drift_ms: optionalNumber(kv.drift_ms),
        });
      } else {
        stop = {
          datetime: parts[0].trim(),
          reason: kv.reason ?? null,
          rows: optionalNumber(kv.rows),
          missed_slots: optionalNumber(kv.missed_slots),
        };
      }
      return;
    }
    if (fieldIndex !== null) return; // other comments after the header carry nothing we use

    const firmware = /firmware\s+([\w.]+)/i.exec(body);
    if (firmware) meta.firmware = firmware[1];
    else if (key === "start_local") meta.start_local = rest;
    else if (key === "rtc") meta.rtc = rest;
    else if (key === "sample_rate_hz") meta.sample_rate_hz = optionalNumber(rest);
    else if (key === "ldc1612") meta.sensor_status = rest;
  }

  function handleDataRow(line: string, index: Record<string, number>) {
    const fields = line.split(",");
    if (fields.length !== fieldCount) {
      malformed++;
      return;
    }
    const elapsed = toNumber(fields[index.elapsed_ms]);
    const sample = toNumber(fields[index.sample]);
    if (!Number.isFinite(elapsed) || !Number.isFinite(sample)) {
      malformed++;
      return;
    }

    const periodMs = 1000 / (meta.sample_rate_hz ?? DEFAULT_SAMPLE_RATE_HZ);
    if (Number.isFinite(prevElapsed)) {
      const interval = elapsed - prevElapsed;
      if (interval > maxInterval) maxInterval = interval;
      if (interval > periodMs * 1.25) lateSamples++;
    } else {
      firstElapsed = elapsed;
    }
    if (Number.isFinite(prevSample) && sample - prevSample > 1) {
      missedSamples += sample - prevSample - 1;
    }
    prevElapsed = elapsed;
    prevSample = sample;

    const L = toNumber(fields[index.ldc_L_uH]);
    const flags = toNumber(fields[index.ldc_flags]);
    if (Number.isFinite(L)) sensorRows++;
    if (Number.isFinite(flags) && flags !== 0) flaggedRows++;

    const datetime = index.datetime !== undefined ? fields[index.datetime].trim() : "";
    if (firstDatetime === null) firstDatetime = datetime;
    lastDatetime = datetime;

    columns.elapsed_ms.push(elapsed);
    columns.sample.push(sample);
    columns.ldc_L_uH.push(L);
    columns.ldc_freq_hz.push(toNumber(fields[index.ldc_freq_hz]));
    columns.ldc_flags.push(flags);
    columns.a0_raw.push(toNumber(fields[index.a0_raw]));
  }

  function handleLine(rawLine: string) {
    const line = rawLine.replace(/\r$/, ""); // tolerate Windows line endings
    if (line.trim() === "") return;
    if (line.startsWith("#")) {
      handleComment(line);
      return;
    }
    if (fieldIndex === null) {
      // The first non-comment line is the column header.
      const names = line.split(",").map((n) => n.trim());
      fieldIndex = Object.fromEntries(names.map((n, i) => [n, i]));
      fieldCount = names.length;
      if (fieldIndex.elapsed_ms === undefined || fieldIndex.sample === undefined) {
        throw new Error("This doesn't look like a Night Night recording: no elapsed_ms/sample columns.");
      }
      return;
    }
    handleDataRow(line, fieldIndex);
  }

  return {
    /** Feed the next piece of the file's text. */
    push(text: string) {
      const lines = (pending + text).split("\n");
      pending = lines.pop() ?? ""; // may be an unfinished line
      for (const line of lines) handleLine(line);
    },

    /** Call once after the last chunk. */
    finish(): DeviceRecording {
      if (pending !== "") handleLine(pending);
      pending = "";
      if (fieldIndex === null) {
        throw new Error("No column header found. Is this a Night Night recording?");
      }
      const rowCount = columns.elapsed_ms.length;
      const periodMs = 1000 / (meta.sample_rate_hz ?? DEFAULT_SAMPLE_RATE_HZ);
      return {
        meta,
        stats: {
          row_count: rowCount,
          duration_ms: rowCount === 0 ? 0 : prevElapsed - firstElapsed + periodMs,
          first_datetime: firstDatetime,
          last_datetime: lastDatetime,
          sensor_rows: sensorRows,
          flagged_rows: flaggedRows,
          missed_samples: missedSamples,
          late_samples: lateSamples,
          max_interval_ms: maxInterval,
          malformed_lines: malformed,
        },
        drift_checks: driftChecks,
        stop,
        columns: {
          elapsed_ms: columns.elapsed_ms.toArray(),
          sample: columns.sample.toArray(),
          ldc_L_uH: columns.ldc_L_uH.toArray(),
          ldc_freq_hz: columns.ldc_freq_hz.toArray(),
          ldc_flags: columns.ldc_flags.toArray(),
          a0_raw: columns.a0_raw.toArray(),
        },
      };
    },
  };
}

/** Parse a whole file's text at once (small files and tests). */
export function parseDeviceCsv(text: string): DeviceRecording {
  const parser = createDeviceParser();
  parser.push(text);
  return parser.finish();
}

// --- Which files on the card are recordings -----------------------------------------------

const RECORDING_NAME = /^S\d{8}_\d{6}(_\d{2})?\.csv$/i;
const IGNORED_FOLDERS = ["system volume information", ".trashes", ".spotlight-v100", ".fseventsd"];

/**
 * True for recording files like `S20261026_205511.csv` or `S20261026_205511_01.csv`.
 * `path` may include folders (from a folder pick); anything inside system folders, and
 * macOS `._*` resource files, is ignored.
 */
export function isRecordingFile(path: string): boolean {
  const parts = path.split(/[\\/]/);
  const name = parts[parts.length - 1];
  if (name.startsWith("._")) return false;
  if (parts.some((p) => IGNORED_FOLDERS.includes(p.toLowerCase()))) return false;
  return RECORDING_NAME.test(name);
}

// --- Plain-language verdict for the list ---------------------------------------------------

export type RecordingBadge = "clean" | "check" | "ended_unexpectedly" | "no_sensor";

export interface RecordingIssues {
  badge: RecordingBadge;
  /** Short human-readable notes, most important first. */
  notes: string[];
}

export function describeIssues(rec: DeviceRecording): RecordingIssues {
  const notes: string[] = [];
  const s = rec.stats;
  if (s.sensor_rows === 0) notes.push("No sensor data (inductance columns are blank)");
  if (!rec.stop) notes.push("Ended unexpectedly (no stop line, e.g. power was cut)");
  if (s.missed_samples > 0) notes.push(`${s.missed_samples} missed sample(s)`);
  if (s.late_samples > 0) notes.push(`${s.late_samples} late sample(s), longest gap ${s.max_interval_ms} ms`);
  if (s.flagged_rows > 0) notes.push(`${s.flagged_rows} row(s) with sensor warning flags`);
  if (s.malformed_lines > 0) notes.push(`${s.malformed_lines} unreadable line(s) skipped`);
  if (rec.stop?.missed_slots) notes.push(`Device reported ${rec.stop.missed_slots} missed slot(s)`);

  const badge: RecordingBadge =
    s.sensor_rows === 0
      ? "no_sensor"
      : !rec.stop
        ? "ended_unexpectedly"
        : notes.length > 0
          ? "check"
          : "clean";
  return { badge, notes };
}
