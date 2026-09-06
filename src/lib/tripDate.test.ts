import { describe, expect, test } from "vitest";
import { getTripDateStatus, isoDaysFromToday, todayIso } from "./tripDate";

// 固定"今天"，避免测试在午夜附近运行时出现边界抖动
const today = new Date("2026-09-06T15:30:00+08:00"); // 2026-09-06

describe("getTripDateStatus", () => {
  test("flags past dates as expired", () => {
    const status = getTripDateStatus("2026-06-19", today);

    expect(status.expired).toBe(true);
    expect(status.beyondPresale).toBe(false);
    expect(status.daysFromToday).toBeLessThan(0);
    expect(status.warning).toContain("已过去");
  });

  test("accepts today and the last presale day without warning", () => {
    expect(getTripDateStatus("2026-09-06", today).warning).toBeNull();
    expect(getTripDateStatus(isoDaysFromToday(14, today), today).warning).toBeNull();
  });

  test("flags dates beyond the 15-day presale window", () => {
    const status = getTripDateStatus(isoDaysFromToday(15, today), today);

    expect(status.expired).toBe(false);
    expect(status.beyondPresale).toBe(true);
    expect(status.warning).toContain("预售期");
  });

  test("treats empty or malformed dates as neutral", () => {
    expect(getTripDateStatus("", today)).toEqual({
      daysFromToday: null,
      expired: false,
      beyondPresale: false,
      warning: null,
    });
    expect(getTripDateStatus("not-a-date", today).warning).toBeNull();
  });

  test("todayIso and isoDaysFromToday render Beijing yyyy-mm-dd", () => {
    expect(todayIso(new Date("2026-09-06T23:59:00+08:00"))).toBe("2026-09-06");
    expect(isoDaysFromToday(1, new Date("2026-12-31T08:00:00+08:00"))).toBe("2027-01-01");
  });
});
