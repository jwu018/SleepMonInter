// Cross-check: the TypeScript breathing pipeline must give the same answers as the Python one
// (tools/processing) on the same file. The fixture comes from tools/export_web_processing.py.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { parseDeviceCsv } from "../device/parseDeviceCsv.ts";
import {
  analyzeRecording,
  countCompleteBreaths,
  findPauses,
  relativeAmplitude,
  removeGlitches,
  snrSirDb,
} from "./breathing.ts";
import { median, sosfiltfilt } from "./dsp.ts";
import { BANDPASS } from "./filterCoefficients.ts";

const dir = path.join(import.meta.dirname, "__fixtures__");
const rec = parseDeviceCsv(readFileSync(path.join(dir, "S20261110_140000_fixture.csv"), "utf-8"));
const expected = JSON.parse(readFileSync(path.join(dir, "expected.json"), "utf-8"));
const analysis = analyzeRecording(rec);

test("finds exactly the same peaks and troughs as Python", () => {
  assert.ok(analysis);
  assert.deepEqual(analysis.breaths.peak_idx, expected.peak_idx);
  assert.deepEqual(analysis.breaths.trough_idx, expected.trough_idx);
});

test("the band-pass filter matches scipy's sosfiltfilt numerically", () => {
  assert.ok(analysis);
  for (const [i, value] of Object.entries(expected.filtered_samples as Record<string, number>)) {
    assert.ok(Math.abs(analysis.filtered[Number(i)] - value) < 1e-9, `sample ${i}`);
  }
});

test("counts, rates, amplitude and pauses match Python", () => {
  assert.ok(analysis);
  const fs = analysis.fs_hz;
  const durationS = analysis.n_samples / fs;
  assert.equal(countCompleteBreaths(analysis.breaths, fs, 10, durationS - 5), expected.breath_count_trimmed);
  analysis.rate_per_minute.forEach((v, k) => {
    const e = expected.rate_per_minute[k];
    if (e === null) assert.equal(v, null);
    else assert.ok(v !== null && Math.abs(v - e) < 1e-9, `minute ${k}`);
  });
  assert.ok(Math.abs(median(relativeAmplitude(analysis.filtered, analysis.breaths)) - expected.amplitude_median) < 1e-9);
  const pauses = findPauses(analysis.breaths, fs);
  assert.equal(pauses.length, expected.pauses.length);
  pauses.forEach(([a, b], i) => {
    assert.ok(Math.abs(a - expected.pauses[i][0]) < 1e-9 && Math.abs(b - expected.pauses[i][1]) < 1e-9);
  });
});

test("removeGlitches blanks stuck readings, out-of-range values and spikes", () => {
  const fs = 25;
  const x = new Float64Array(500).map((_, i) => 4 + 0.03 * Math.sin((2 * Math.PI * 0.3 * i) / fs));
  x.fill(4.05, 0, 50); // 2 s stuck
  x[300] = 1970.2;
  const y = removeGlitches(x, fs);
  assert.ok(y.slice(0, 50).every(Number.isNaN));
  assert.ok(Number.isNaN(y[300]));
  assert.ok(Number.isFinite(y[200]));
});

test("sosfiltfilt rejects signals shorter than its padding", () => {
  const { sos, zi } = BANDPASS["25"];
  assert.throws(() => sosfiltfilt(sos, zi, new Float64Array(10)), /too short/);
});

test("no sensor data gives no analysis", () => {
  const noSensor = parseDeviceCsv(
    [
      "# sample_rate_hz,25",
      "datetime,elapsed_ms,sample,ldc_raw,ldc_freq_hz,ldc_L_uH,ldc_flags,a0_raw",
      "2026-10-26 20:55:11.027,0,0,,,,,209",
    ].join("\n"),
  );
  assert.equal(analyzeRecording(noSensor), null);
});

test("SNR, SIR and per-minute quality match Python", () => {
  assert.ok(analysis);
  const fs = analysis.fs_hz;
  const [snr, sir] = snrSirDb(analysis.bands, Math.trunc(10 * fs), Math.trunc((analysis.n_samples / fs - 5) * fs), fs);
  assert.ok(Math.abs(snr - expected.snr_db_trimmed) < 1e-6, `snr ${snr}`);
  assert.ok(Math.abs(sir - expected.sir_db_trimmed) < 1e-6, `sir ${sir}`);
  assert.equal(analysis.quality.length, expected.quality.length);
  analysis.quality.forEach((w, k) => {
    const e = expected.quality[k];
    assert.equal(w.label, e.label, `minute ${k}`);
    assert.ok(Math.abs(w.snr_db - e.snr_db) < 1e-6 && Math.abs(w.sir_db - e.sir_db) < 1e-6, `minute ${k}`);
  });
});
