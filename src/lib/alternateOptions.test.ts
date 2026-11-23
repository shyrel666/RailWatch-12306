import { expect, test } from "vitest";
import { alternateConfigIssue, alternateDates, canonicalDeadline } from "./alternateOptions";
import { defaultConfig } from "../store/railwatchStore";

test("only equivalent relative deadlines migrate", () => {
  expect(canonicalDeadline("开车前60分钟")).toBe("开车前1小时");
  expect(canonicalDeadline("开车前48小时")).toBe("开车前2天");
  expect(canonicalDeadline("2026-10-10 18:00")).toBe("2026-10-10 18:00");
  expect(alternateConfigIssue({ ...defaultConfig, auto_alternate: true, alternate_deadline: "18:00" })).toContain("仅支持官网提供的选项");
});

test("waitlist dates and new-train windows use the ordered custom dates", () => {
  const config = { ...defaultConfig, date: "2026-10-10", date_range: "自定义",
    custom_dates: ["2026-10-20", "2026-10-10", "2026-10-12"], auto_alternate: true, alternate_accept_new_trains: true };
  const window = { date: "2026-10-20", start_hour: 8, end_hour: 22 };
  expect(alternateDates(config)).toEqual(config.custom_dates);
  expect(alternateConfigIssue({ ...config, alternate_new_train_windows: [window] })).toBeNull();
  expect(alternateConfigIssue({ ...config, alternate_new_train_windows: [{ ...window, date: "2026-10-11" }] })).toContain("日期范围");
});

test("new-train constraints reject missing, duplicate, reversed or out-of-trip windows", () => {
  const config = { ...defaultConfig, date: "2026-10-10", date_range: "单日", auto_alternate: true, alternate_accept_new_trains: true };
  const valid = { date: "2026-10-10", start_hour: 8, end_hour: 22 };
  expect(alternateConfigIssue(config)).toContain("至少一个");
  expect(alternateConfigIssue({ ...config, alternate_new_train_windows: [valid] })).toBeNull();
  expect(alternateConfigIssue({ ...config, alternate_new_train_windows: [valid, valid] })).toContain("重复");
  expect(alternateConfigIssue({ ...config, alternate_new_train_windows: [{ ...valid, end_hour: 7 }] })).toContain("开始早于结束");
  expect(alternateConfigIssue({ ...config, alternate_new_train_windows: [{ ...valid, date: "2026-10-11" }] })).toContain("日期范围");
});
