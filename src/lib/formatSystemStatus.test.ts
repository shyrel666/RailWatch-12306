import { describe, expect, test } from "vitest";
import { formatAppVersion, formatDataDirFreeSpace, formatDataDirPath, formatRuntimePhase, formatRuntimePhaseDetail, formatRuntimePhaseLabel, formatStatusClock, getRuntimePhaseTone } from "./formatSystemStatus";

describe("formatSystemStatus", () => {
  test("formats app versions with a v prefix", () => {
    expect(formatAppVersion("0.1.0")).toBe("v0.1.0");
    expect(formatAppVersion("v1.3.0")).toBe("v1.3.0");
    expect(formatAppVersion("未知")).toBe("未知");
  });

  test("wraps data directory paths at separators for sidebar display", () => {
    expect(formatDataDirPath("")).toBe("正在加载...");
    expect(formatDataDirPath("C:\\Users\\demo\\railwatch-12306")).toContain("\u200b");
  });

  test("formats disk free space for sidebar display", () => {
    expect(formatDataDirFreeSpace(128_600_000_000)).toBe("119.8 GB");
    expect(formatDataDirFreeSpace(512_000_000)).toBe("488 MB");
    expect(formatDataDirFreeSpace(0)).toBe("未知");
  });

  test("prefers runtime status messages over generic phase labels", () => {
    expect(formatRuntimePhaseLabel("环境就绪", "environment")).toBe("环境就绪");
    expect(formatRuntimePhaseLabel("已解析 53 行查询结果", "query_ready")).toBe("查询就绪");
    expect(formatRuntimePhaseDetail("已解析 53 行查询结果", "query_ready")).toBe("已解析 53 行查询结果");
    expect(formatRuntimePhase("", "error")).toBe("需处理");
  });

  test("formats a live clock for the sidebar runtime card", () => {
    const clock = formatStatusClock(new Date("2026-06-07T19:50:46"));

    expect(clock).toEqual({
      date: "2026-06-07",
      yearMonth: "2026-06",
      day: "07",
      weekday: "周日",
      hours: "19",
      minutes: "50",
      seconds: "46",
      time: "19:50:46",
    });
    expect(getRuntimePhaseTone("monitoring")).toBe("active");
  });
});
