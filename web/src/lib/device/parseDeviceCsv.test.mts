// Run with: npm test   (Node's built-in test runner; Node runs TypeScript directly)
import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import {
  createDeviceParser,
  describeIssues,
  isRecordingFile,
  parseDeviceCsv,
} from "./parseDeviceCsv.ts";
import { deviceClockTime, formatElapsed, tracePoints } from "./trace.ts";

const HEADER_NO_SENSOR = [
  "# Night Night respiratory logger, firmware 0.1",
  "# start_local,2026-10-26 20:55:11",
  "# rtc,DS3231 ok",
  "# sample_rate_hz,25",
  "# ldc1612,NOT FOUND (sensor columns blank)",
  "datetime,elapsed_ms,sample,ldc_raw,ldc_freq_hz,ldc_L_uH,ldc_flags,a0_raw",
].join("\n");

const WITH_SENSOR = [
  "# Night Night respiratory logger, firmware 0.2",
  "# start_local,2026-10-26 23:59:58",
  "# rtc,DS3231 ok",
  "# sample_rate_hz,25",
  "# ldc1612,channel 0, tank 100 pF, drive 20",
  "datetime,elapsed_ms,sample,ldc_raw,ldc_freq_hz,ldc_L_uH,ldc_flags,a0_raw",
  "2026-10-26 23:59:58.000,0,0,21735392,3238825.8,24.14711,0,161",
  "2026-10-26 23:59:58.040,40,1,21735413,3238828.9,24.14706,0,669",
  "# drift_check,2026-10-26 23:59:58.060,elapsed_ms=60,drift_ms=2,resolution_ms=+/-20",
  "2026-10-26 23:59:58.080,80,2,21735420,3238830.0,24.14700,1,650",
  "# stop,2026-10-26 23:59:58.100,reason=serial,rows=3,missed_slots=0",
].join("\n");

test("reads header metadata and a file with no sensor and no stop line", () => {
  const text = `${HEADER_NO_SENSOR}\n2026-10-26 20:55:11.027,0,0,,,,,209\n2026-10-26 20:55:11.067,40,1,,,,,691\n`;
  const rec = parseDeviceCsv(text);
  assert.equal(rec.meta.firmware, "0.1");
  assert.equal(rec.meta.start_local, "2026-10-26 20:55:11");
  assert.equal(rec.meta.sample_rate_hz, 25);
  assert.match(rec.meta.sensor_status ?? "", /NOT FOUND/);
  assert.equal(rec.stats.row_count, 2);
  assert.equal(rec.stats.sensor_rows, 0);
  assert.ok(Number.isNaN(rec.columns.ldc_L_uH[0]));
  assert.equal(rec.columns.a0_raw[1], 691);
  assert.equal(rec.stop, null);

  const issues = describeIssues(rec);
  assert.equal(issues.badge, "no_sensor");
  assert.ok(issues.notes.some((n) => n.startsWith("Ended unexpectedly")));
});

test("reads sensor values, flags, drift checks and the stop line", () => {
  const rec = parseDeviceCsv(WITH_SENSOR);
  assert.equal(rec.stats.row_count, 3);
  assert.equal(rec.stats.sensor_rows, 3);
  assert.equal(rec.columns.ldc_L_uH[1], 24.14706);
  assert.equal(rec.stats.flagged_rows, 1);
  assert.deepEqual(rec.drift_checks, [
    { datetime: "2026-10-26 23:59:58.060", elapsed_ms: 60, drift_ms: 2 },
  ]);
  assert.deepEqual(rec.stop, {
    datetime: "2026-10-26 23:59:58.100",
    reason: "serial",
    rows: 3,
    missed_slots: 0,
  });
  assert.equal(rec.stats.duration_ms, 120); // 80 ms span + one 40 ms period
  assert.equal(describeIssues(rec).badge, "check"); // because of the flagged row
});

test("counts missed samples from index jumps and late samples from long intervals", () => {
  const rows = [
    "2026-10-26 20:58:02.000,0,0,,,1,0,1",
    "2026-10-26 20:58:02.040,40,1,,,1,0,1",
    "2026-10-26 20:58:02.160,160,4,,,1,0,1", // samples 2 and 3 missing
    "2026-10-26 20:58:02.218,218,5,,,1,0,1", // 58 ms: late
    "2026-10-26 20:58:02.240,240,6,,,1,0,1", // 22 ms catch-up: fine
    "# stop,2026-10-26 20:58:02.250,reason=serial,rows=5,missed_slots=2",
  ];
  const rec = parseDeviceCsv(`${HEADER_NO_SENSOR}\n${rows.join("\n")}`);
  assert.equal(rec.stats.missed_samples, 2);
  assert.equal(rec.stats.late_samples, 2); // the 120 ms jump and the 58 ms one
  assert.equal(rec.stats.max_interval_ms, 120);
  assert.equal(describeIssues(rec).badge, "check");
});

test("gives the same result however the text is split into chunks", () => {
  const whole = parseDeviceCsv(WITH_SENSOR);
  for (const size of [1, 7, 50]) {
    const parser = createDeviceParser();
    for (let i = 0; i < WITH_SENSOR.length; i += size) parser.push(WITH_SENSOR.slice(i, i + size));
    const chunked = parser.finish();
    assert.deepEqual(chunked.stats, whole.stats, `chunk size ${size}`);
    assert.deepEqual(Array.from(chunked.columns.ldc_L_uH), Array.from(whole.columns.ldc_L_uH));
    assert.deepEqual(chunked.stop, whole.stop);
  }
});

test("tolerates Windows line endings", () => {
  const rec = parseDeviceCsv(WITH_SENSOR.replaceAll("\n", "\r\n"));
  assert.equal(rec.stats.row_count, 3);
  assert.equal(rec.stop?.reason, "serial");
});

test("skips malformed rows instead of failing", () => {
  const rec = parseDeviceCsv(`${HEADER_NO_SENSOR}\n2026-10-26 20:55:11.027,0,0,,,,,209\ngarbage\n`);
  assert.equal(rec.stats.row_count, 1);
  assert.equal(rec.stats.malformed_lines, 1);
});

test("rejects a file that isn't a recording", () => {
  assert.throws(() => parseDeviceCsv("hello,world\n1,2\n"), /doesn't look like/);
  assert.throws(() => parseDeviceCsv("# just a comment\n"), /No column header/);
});

test("recognises recording files and ignores everything else on the card", () => {
  assert.ok(isRecordingFile("S20261026_205511.csv"));
  assert.ok(isRecordingFile("SDCARD/S20261026_205511_01.csv"));
  assert.ok(!isRecordingFile("sdtest.csv"));
  assert.ok(!isRecordingFile("._S20261026_205511.csv"));
  assert.ok(!isRecordingFile("System Volume Information/S20261026_205511.csv"));
  assert.ok(!isRecordingFile("S2026_1.csv"));
});

test("tracePoints returns raw points when zoomed in and min/max pairs when zoomed out", () => {
  const t = new Float64Array(Array.from({ length: 1000 }, (_, i) => i * 40));
  const v = new Float64Array(Array.from({ length: 1000 }, (_, i) => (i === 500 ? 99 : i % 2)));
  const raw = tracePoints(t, v, 0, 400, 100);
  assert.equal(raw.resolution, "raw");
  assert.equal(raw.x.length, 10);

  const env = tracePoints(t, v, 0, 40_000, 100);
  assert.equal(env.resolution, "envelope");
  assert.ok(env.x.length <= 100);
  assert.ok(env.y.includes(99), "the one-sample spike must survive downsampling");
});

test("tracePoints breaks the line across a data gap", () => {
  const t = new Float64Array([0, 40, 80, 5080, 5120]);
  const v = new Float64Array([1, 2, 3, 4, 5]);
  const pts = tracePoints(t, v, 0, 10_000, 100);
  assert.ok(pts.y.includes(null));
});

test("device clock time is plain clock arithmetic, including past midnight", () => {
  assert.equal(deviceClockTime("2026-10-26 23:59:58", 0), "23:59:58");
  assert.equal(deviceClockTime("2026-10-26 23:59:58", 3), "00:00:01");
  assert.equal(deviceClockTime(null, 3), null);
  assert.equal(formatElapsed(67.2), "1:07");
  assert.equal(formatElapsed(3723), "1:02:03");
});

// Real bench files from the firmware team. They're gitignored, so this only runs locally.
const IRL_DIR = path.resolve(import.meta.dirname, "../../../../irl_sample_data");
test("parses the firmware team's bench recordings", { skip: !existsSync(IRL_DIR) }, () => {
  const files = readdirSync(IRL_DIR).filter(isRecordingFile);
  assert.ok(files.length > 0);
  for (const name of files) {
    const rec = parseDeviceCsv(readFileSync(path.join(IRL_DIR, name), "utf-8"));
    assert.ok(rec.stats.row_count > 0, name);
    assert.equal(rec.stats.malformed_lines, 0, name);
    assert.equal(rec.stats.missed_samples, 0, name);
    if (rec.stop?.rows != null) assert.equal(rec.stats.row_count, rec.stop.rows, name);
  }
});
