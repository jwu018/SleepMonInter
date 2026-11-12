import assert from "node:assert/strict";
import { test } from "node:test";
import { alignByClock, clockLabel, hoursAfterNoon } from "./clockAxis.ts";

test("hoursAfterNoon keeps a night increasing across midnight", () => {
  assert.equal(hoursAfterNoon(22, 0), 10);
  assert.equal(hoursAfterNoon(0, 30), 12.5);
  assert.equal(hoursAfterNoon(7, 0), 19);
  assert.ok(hoursAfterNoon(23, 59) < hoursAfterNoon(0, 1));
});

test("clockLabel turns axis values back into clock times", () => {
  assert.equal(clockLabel(10), "10 pm");
  assert.equal(clockLabel(12), "12 am");
  assert.equal(clockLabel(19.5), "7:30 am");
  assert.equal(clockLabel(0), "12 pm");
});

test("alignByClock lines up nights that started at different times", () => {
  // Night A starts 22:00 (x=10), night B starts 22:02 (x=10.0333).
  const { x, series } = alignByClock([
    { start_x: 10, values: [1, 2, 3] },
    { start_x: 10 + 2 / 60, values: [7, 8] },
  ]);
  assert.equal(x.length, 4);
  assert.deepEqual(series[0], [1, 2, 3, null]);
  assert.deepEqual(series[1], [null, null, 7, 8]);
});
