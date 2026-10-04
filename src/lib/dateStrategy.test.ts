import { expect, test } from "vitest";
import { defaultConfig } from "../store/railwatchStore";
import { dateStrategy, dateStrategySummary } from "./dateStrategy";

test("old settings retain chronological waitlist behavior and explain unchecked dates", () => {
  const config = { ...defaultConfig, date_strategy: undefined };
  expect(dateStrategy(config)).toBe("round_robin");
  expect(dateStrategySummary(config)).toContain("后续日期可能尚未查询");
});

test("cash-first budget explains fresh recheck and timed focus", () => {
  expect(dateStrategySummary({ ...defaultConfig, date_strategy: "inventory_first", date_scan_budget_seconds: 45,
    timer_enabled: true })).toContain("扫描预算45秒");
  expect(dateStrategySummary({ ...defaultConfig, date_strategy: "inventory_first", timer_enabled: true }))
    .toContain("起售窗口内集中查询所选日期");
  expect(dateStrategySummary({ ...defaultConfig, date_range: "单日" })).toContain("仅查询所选日期");
});
