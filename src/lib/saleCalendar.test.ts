import { describe, expect, test } from "vitest";
import type { StationSaleTimes } from "../types";
import { calendarDays, countdown, presaleDays, saleDay, SALE_TIME_SOURCE } from "./saleCalendar";

const now = Date.parse("2026-09-27T09:59:59+08:00");
export const saleInfo = (station = "北京", timestamp = now): StationSaleTimes => ({
  station, status: "available", checked_at: timestamp / 1000 - 10, expires_at: timestamp / 1000 + 3590,
  retry_at: timestamp / 1000 + 50, warning: null, source_url: SALE_TIME_SOURCE,
  schedules: [{ station_name: station, station_code: "BJP", sale_time: "10:00", start_date: "2010-01-01", stop_date: "2099-12-31" }],
});

describe("sale calendar", () => {
  test("includes today and 14 following days, then a planning week", () => {
    const dates = calendarDays(now, 15);
    expect(dates).toHaveLength(22);
    expect(dates[0]).toBe("2026-09-27");
    expect(dates[14]).toBe("2026-10-11");
    expect(saleDay(dates[15], now, 15, saleInfo()).state).toBe("future");
  });
  test("changes only at the actual sale instant", () => {
    expect(saleDay("2026-10-11", now, 15, saleInfo())).toMatchObject({ state: "waiting", releaseDate: "2026-09-27", time: "10:00" });
    expect(saleDay("2026-10-11", now + 1000, 15, saleInfo()).state).toBe("open");
    expect(countdown(now + 1000, now)).toBe("00:00:01");
    expect(countdown(now, now + 1000)).toBe("00:00:00");
  });
  test("unknown and stale data never supply a sale instant", () => {
    for (const info of [null, { ...saleInfo(), status: "stale" as const }, { ...saleInfo(), expires_at: now / 1000 }]) {
      expect(saleDay("2026-10-11", now, 15, info)).toMatchObject({ state: "unknown", saleAt: null });
    }
    expect(saleDay("2026-10-10", now, 15, null).state).toBe("window");
  });
  test("rejects conflicting, out-of-period and boundary schedules", () => {
    const info = saleInfo();
    info.schedules.push({ ...info.schedules[0], sale_time: "11:00" });
    expect(saleDay("2026-10-11", now, 15, info).saleAt).toBeNull();
    info.schedules = [{ ...info.schedules[0], start_date: "2026-09-27" }];
    expect(saleDay("2026-10-11", now, 15, info).saleAt).toBeNull();
    info.schedules[0].start_date = "2026-10-01";
    expect(saleDay("2026-10-11", now, 15, info).saleAt).toBeNull();
  });
  test("rolls over at Beijing midnight regardless of local timezone", () => {
    expect(calendarDays(Date.parse("2026-12-31T15:59:59Z"), 15)[0]).toBe("2026-12-31");
    expect(calendarDays(Date.parse("2026-12-31T16:00:00Z"), 15)[0]).toBe("2027-01-01");
    expect(saleDay("2027-01-14", now, 15, null).releaseDate).toBe("2026-12-31");
    expect(saleDay("2028-03-14", now, 15, null).releaseDate).toBe("2028-02-29");
  });
  test("handles invalid dates, expired trips and changed policy", () => {
    expect(saleDay("2026-02-30", now, 15, null).state).toBe("invalid");
    expect(saleDay("", now, 15, null).state).toBe("invalid");
    expect(saleDay("2026-09-26", now, 15, saleInfo()).state).toBe("expired");
    expect(saleDay("2026-10-11", now, 10, saleInfo()).releaseDate).toBe("2026-10-02");
    expect(presaleDays(0)).toBe(15);
    expect(presaleDays(NaN)).toBe(15);
  });
});

import sharedSaleCases from "../../tests/fixtures/sale-time-cases.json";
test("matches the backend shared sale time cases", () => {
  for (const item of sharedSaleCases) {
    const result = saleDay(item.date, Date.parse(item.now), item.window_days, item.info as StationSaleTimes);
    expect(result.saleAt, item.name).toBe(item.expected ? Date.parse(item.expected) : null);
  }
});
