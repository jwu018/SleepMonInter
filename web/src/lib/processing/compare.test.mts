import assert from "node:assert/strict";
import { test } from "node:test";
import { alignSeries, breathByBreathRate, deviceStartAfterNoonS, medianBreathDepth } from "./compare.ts";

test("breath-by-breath rate is 60 / time between troughs", () => {
  // Troughs at 0 s, 4 s, 7 s (25 Hz): intervals 4 s and 3 s -> 15 and 20 breaths/min.
  const r = breathByBreathRate({ peak_idx: [], trough_idx: [0, 100, 175] }, 25, 10);
  assert.deepEqual(r.x, [14, 17]);
  assert.deepEqual(r.y, [15, 20]);
});

test("median breath depth uses the trough before each peak", () => {
  const f = new Float64Array([-1, 0, 2, 0, -2, 0, 1]);
  // Peaks at 2 and 6; troughs at 0 and 4. Depths: 2-(-1)=3 and 1-(-2)=3.
  assert.equal(medianBreathDepth(f, { peak_idx: [2, 6], trough_idx: [0, 4] }), 3);
});

test("alignSeries merges x values and leaves gaps as null", () => {
  const { x, ys } = alignSeries([
    { x: [0, 2], y: [1, 2] },
    { x: [1, 2], y: [5, 6] },
  ]);
  assert.deepEqual(x, [0, 1, 2]);
  assert.deepEqual(ys, [
    [1, null, 2],
    [null, 5, 6],
  ]);
});

test("device clock start maps evenings and early mornings onto one increasing axis", () => {
  assert.equal(deviceStartAfterNoonS("2026-11-03 22:00:00"), 10 * 3600);
  assert.equal(deviceStartAfterNoonS("2026-11-04 01:30:00"), 13.5 * 3600);
  assert.equal(deviceStartAfterNoonS(null), null);
});
