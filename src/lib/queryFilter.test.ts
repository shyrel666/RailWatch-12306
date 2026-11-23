import { describe, expect, test } from "vitest";
import type { QueryResultRow, SeatAvailability, StructuredQueryResultRow } from "../types";
import {
  defaultQueryFilter, departurePeriod, durationMinutes, filterAndSortRows, formatDuration, isQueryFilterActive, trainCategory,
  type QueryFilter,
} from "./queryFilter";

function row(train: string, fields: Partial<StructuredQueryResultRow> = {}): StructuredQueryResultRow {
  return {
    date: "2026-11-27",
    train,
    raw: "",
    from_station: null,
    to_station: null,
    departure_time: null,
    arrival_time: null,
    arrival_day_offset: null,
    seats: {},
    ...fields,
  };
}

const available: SeatAvailability = { status: "available", count: 2, raw: "2" };
const alternate: SeatAvailability = { status: "alternate", count: null, raw: "候补" };
const unavailable: SeatAvailability = { status: "unavailable", count: 0, raw: "无" };
const unknown: SeatAvailability = { status: "unknown", count: null, raw: "*" };
const notApplicable: SeatAvailability = { status: "not_applicable", count: null, raw: "不适用" };

describe("query time helpers", () => {
  test("computes elapsed minutes using the observed arrival day", () => {
    expect(durationMinutes("06:20", "07:30", 0)).toBe(70);
    expect(durationMinutes("23:55", "00:05", 1)).toBe(10);
    expect(durationMinutes("23:55", "00:05", 2)).toBe(1450);
  });

  test("does not infer a duration from incomplete or inconsistent fields", () => {
    expect(durationMinutes(null, "07:30", 0)).toBeNull();
    expect(durationMinutes("06:20", undefined, 0)).toBeNull();
    expect(durationMinutes("06:20", "07:30", null)).toBeNull();
    expect(durationMinutes("06:20", "07:30")).toBeNull();
    expect(durationMinutes("06:20", "06:20", 0)).toBeNull();
    expect(durationMinutes("23:55", "00:05", 0)).toBeNull();
    expect(durationMinutes("23:55", "00:05", -1)).toBeNull();
    expect(durationMinutes("23:55", "00:05", 1.5)).toBeNull();
    expect(durationMinutes("06:20", "07:30", Infinity)).toBeNull();
    expect(durationMinutes("06:20", "07:30", Number.MAX_SAFE_INTEGER)).toBeNull();
    expect(durationMinutes("6:20", "07:30", 0)).toBeNull();
    expect(durationMinutes("06:20", "24:00", 0)).toBeNull();
    expect(durationMinutes("06:60", "07:30", 0)).toBeNull();
  });

  test("formats minutes and hours without zero units", () => {
    expect(formatDuration(0)).toBe("0分钟");
    expect(formatDuration(45)).toBe("45分钟");
    expect(formatDuration(120)).toBe("2小时");
    expect(formatDuration(125)).toBe("2小时5分");
    expect(formatDuration(1450)).toBe("24小时10分");
  });

  test("assigns all boundary times to their exact departure periods", () => {
    expect(departurePeriod("00:00")).toBe("night");
    expect(departurePeriod("05:59")).toBe("night");
    expect(departurePeriod("06:00")).toBe("morning");
    expect(departurePeriod("11:59")).toBe("morning");
    expect(departurePeriod("12:00")).toBe("afternoon");
    expect(departurePeriod("17:59")).toBe("afternoon");
    expect(departurePeriod("18:00")).toBe("evening");
    expect(departurePeriod("23:59")).toBe("evening");
    expect(departurePeriod(null)).toBeNull();
    expect(departurePeriod()).toBeNull();
    expect(departurePeriod("24:00")).toBeNull();
  });
});

describe("train and query filters", () => {
  test("classifies the fixed code families case-insensitively and trims whitespace", () => {
    expect([" x1 ", "G101", "d2", "C3", "s4"].map(code => trainCategory(code))).toEqual(Array(5).fill("highspeed"));
    expect([" z10 ", "N2", "v3"].map(code => trainCategory(code))).toEqual(Array(3).fill("normal"));
    expect(["Y5", " l6 ", "1234", "", "Q8"].map(code => trainCategory(code))).toEqual(Array(5).fill("other"));
  });

  test.each([" t11 ", "K12"])("classifies %s using only applicable structured seat evidence", code => {
    expect(trainCategory(code)).toBe("highspeed");
    expect(trainCategory(code, { 二等座: available })).toBe("highspeed");
    expect(trainCategory(code, { 硬座: unknown, 硬卧: notApplicable })).toBe("highspeed");
    expect(trainCategory(code, { 硬座: available, 二等座: unknown })).toBe("normal");
    expect(trainCategory(code, { 硬卧: unavailable, 二等座: notApplicable })).toBe("normal");
    expect(trainCategory(code, { 硬卧: alternate })).toBe("normal");
    for (const seat of ["商务座", "特等座", "一等座", "二等座", "动卧"]) {
      expect(trainCategory(code, { 硬座: available, [seat]: unavailable })).toBe("highspeed");
      expect(trainCategory(code, { 硬座: available, [seat]: alternate })).toBe("highspeed");
    }
  });

  test("defaults preserve all rows and tracks filter or sort changes", () => {
    const results: readonly QueryResultRow[] = [row("G101"), { train: "X3", raw: "旧版数据" }, row("K22")];
    expect(filterAndSortRows(results, defaultQueryFilter, ["二等座"])).toEqual(results);
    expect(isQueryFilterActive(defaultQueryFilter)).toBe(false);
    const changes: Partial<QueryFilter>[] = [
      { category: "other" }, { period: "morning" }, { availability: "available" }, { fromStation: "北京西" }, { sort: "arrival" },
    ];
    for (const change of changes) expect(isQueryFilterActive({ ...defaultQueryFilter, ...change })).toBe(true);
  });

  test("intersects train category, departure period, actual station and selected-seat availability", () => {
    const morning = { from_station: " 北京西 ", departure_time: "08:00", seats: { 二等座: available } };
    const results = [
      row("G101", morning),
      row("K102", morning),
      row("G103", { ...morning, departure_time: "13:00" }),
      row("G104", { ...morning, from_station: "北京南" }),
      row("G105", { ...morning, from_station: null }),
      row("G106", { ...morning, seats: { 二等座: alternate } }),
      row("Z107", morning),
    ];
    const filter: QueryFilter = {
      ...defaultQueryFilter, category: "highspeed", period: "morning", fromStation: "北京西", availability: "available",
    };
    expect(filterAndSortRows(results, filter, ["二等座"]).map(({ train }) => train)).toEqual(["G101", "K102"]);
    expect(filterAndSortRows(results, { ...filter, period: "evening" }, ["二等座"])).toEqual([]);
  });

  test("available and waitlist-only seats differ, and unknown data never implies availability", () => {
    const results = [
      row("G101", { seats: { 二等座: available } }),
      row("G102", { seats: { 二等座: alternate, 一等座: available } }),
      row("G103", { seats: { 二等座: unavailable } }),
      row("G104", { seats: { 二等座: { status: "unknown", count: null, raw: "*" } } }),
      row("G105", { seats: { 二等座: { status: "not_applicable", count: null, raw: "不适用" } } }),
      { train: "G106", raw: "旧版行显示有余票" },
    ];
    const availableOnly = { ...defaultQueryFilter, availability: "available" } as const;
    const availableOrWaitlist = { ...defaultQueryFilter, availability: "available_or_alternate" } as const;
    expect(filterAndSortRows(results, availableOnly, ["二等座"]).map(({ train }) => train)).toEqual(["G101"]);
    expect(filterAndSortRows(results, availableOrWaitlist, ["二等座"]).map(({ train }) => train)).toEqual(["G101", "G102"]);
    expect(filterAndSortRows(results, availableOnly, ["二等座", "一等座"]).map(({ train }) => train)).toEqual(["G101", "G102"]);
    expect(filterAndSortRows(results, availableOnly, []).map(({ train }) => train)).toEqual(["G101", "G102"]);
  });

  test("sorts stably by known times and durations, placing unknown values last", () => {
    const overnight = row("G101", { departure_time: "22:00", arrival_time: "00:20", arrival_day_offset: 1 });
    const late = row("G102", { departure_time: "22:00", arrival_time: "23:45", arrival_day_offset: 0 });
    const early = row("G103", { departure_time: "05:30", arrival_time: "20:00", arrival_day_offset: 0 });
    const missing = row("G104", { arrival_day_offset: 0 });
    const unknownDay = row("G105", { departure_time: "10:00", arrival_time: "12:00" });
    const results = Object.freeze([overnight, late, early, missing, unknownDay]);
    expect(filterAndSortRows(results, { ...defaultQueryFilter, sort: "departure" }, []))
      .toEqual([early, unknownDay, overnight, late, missing]);
    expect(filterAndSortRows(results, { ...defaultQueryFilter, sort: "arrival" }, []))
      .toEqual([early, late, overnight, missing, unknownDay]);
    expect(filterAndSortRows(results, { ...defaultQueryFilter, sort: "duration" }, []))
      .toEqual([late, overnight, early, missing, unknownDay]);
  });
});
