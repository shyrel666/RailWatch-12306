import { expect, test } from "vitest";
import { msTick, niceTicks, span } from "./chartScale";

test("ticks start at zero, cover the maximum and use round steps", () => {
  expect(niceTicks(7600)).toEqual([0, 2000, 4000, 6000, 8000]);
  expect(niceTicks(1090)).toEqual([0, 250, 500, 750, 1000, 1250]);
  expect(niceTicks(30)).toEqual([0, 10, 20, 30]);
  expect(niceTicks(0)).toEqual([0, 1]);
  expect(niceTicks(Number.NaN)).toEqual([0, 1]);
});

test("tick labels switch the whole axis to seconds once it reaches one second", () => {
  const short = niceTicks(480);
  expect(short.map(value => msTick(value, short))).toEqual(["0", "100ms", "200ms", "300ms", "400ms", "500ms"]);
  const long = niceTicks(1090);
  expect(long.map(value => msTick(value, long))).toEqual(["0", "0.25s", "0.5s", "0.75s", "1s", "1.25s"]);
});

test("spans stay precise when short and readable when long", () => {
  expect(span(8420)).toBe("8.42 秒");
  expect(span(22000)).toBe("22.0 秒");
  expect(span(125000)).toBe("2 分 05 秒");
  expect(span(119600)).toBe("2 分 00 秒");
});
