import { describe, expect, test } from "vitest";
import type { UpdateRuntimeState } from "../types";
import { formatBytes, formatReleaseDate, formatRemaining, formatTransfer, getUpdateFacts, getUpdateSignal } from "./updateDisplay";

const base: UpdateRuntimeState = { phase: "idle", currentVersion: "0.7.0", installMode: "auto" };

describe("getUpdateSignal", () => {
  test("is amber while pending, green when ready and red on failure", () => {
    expect(getUpdateSignal(base)).toEqual({ tone: "idle", live: false });
    expect(getUpdateSignal({ ...base, phase: "checking" })).toEqual({ tone: "wait", live: true });
    expect(getUpdateSignal({ ...base, phase: "available" })).toEqual({ tone: "wait", live: true });
    expect(getUpdateSignal({ ...base, phase: "available", installMode: "manual" })).toEqual({ tone: "wait", live: false });
    expect(getUpdateSignal({ ...base, phase: "downloading" })).toEqual({ tone: "wait", live: true });
    expect(getUpdateSignal({ ...base, phase: "downloaded" })).toEqual({ tone: "go", live: false });
    expect(getUpdateSignal({ ...base, phase: "not-available" })).toEqual({ tone: "go", live: false });
    expect(getUpdateSignal({ ...base, phase: "error" })).toEqual({ tone: "stop", live: false });
  });

  test("a deferred or starting installation is pending, not ready", () => {
    expect(getUpdateSignal({ ...base, phase: "downloaded", error: "当前存在活动任务，更新已推迟。" })).toEqual({ tone: "wait", live: false });
    expect(getUpdateSignal({ ...base, phase: "downloaded" }, true)).toEqual({ tone: "wait", live: true });
  });
});

describe("download formatting", () => {
  test("formats sizes, shared-unit transfers and remaining time", () => {
    expect(formatBytes(512 * 1024)).toBe("512 KB");
    expect(formatBytes(98_100_000)).toBe("93.6 MB");
    expect(formatBytes(1.5 * 1024 ** 3)).toBe("1.50 GB");
    expect(formatTransfer(41_590_000, 98_100_000)).toBe("39.7 / 93.6 MB");
    expect(formatTransfer(200_000, 98_100_000)).toBe("0.2 / 93.6 MB");
    expect(formatTransfer(3_000_000)).toBe("2.9 MB");
    expect(formatRemaining(2)).toBe("即将完成");
    expect(formatRemaining(23)).toBe("约 25 秒");
    expect(formatRemaining(150)).toBe("约 3 分钟");
    expect(formatRemaining(5400)).toBe("约 1.5 小时");
    expect(formatRemaining(Number.POSITIVE_INFINITY)).toBe("");
  });

  test("lists transfer facts only while they are known", () => {
    const downloading: UpdateRuntimeState = { ...base, phase: "downloading", downloadPercent: 42,
      downloadTransferred: 41_590_000, downloadTotal: 98_100_000, downloadSpeed: 2_300_000 };

    expect(getUpdateFacts(downloading)).toEqual([
      { label: "已下载", value: "39.7 / 93.6 MB" },
      { label: "速度", value: "2.2 MB/s" },
      { label: "剩余", value: "约 25 秒" },
    ]);
    expect(getUpdateFacts({ ...downloading, downloadSpeed: 0 })).toEqual([{ label: "已下载", value: "39.7 / 93.6 MB" }]);
    expect(getUpdateFacts({ ...base, phase: "downloading", downloadPercent: 42 })).toEqual([]);
    expect(getUpdateFacts({ ...base, phase: "downloaded", packageSize: 98_100_000 })).toEqual([{ label: "安装包", value: "93.6 MB" }]);
    expect(getUpdateFacts({ ...base, phase: "downloaded" })).toEqual([]);
  });

  test("shows release days in Beijing time and adds the year only for other years", () => {
    const now = new Date("2026-10-13T04:00:00Z");
    expect(formatReleaseDate("2026-10-12T17:30:00Z", now)).toBe("10月13日");
    expect(formatReleaseDate("2025-12-31T08:00:00Z", now)).toBe("2025年12月31日");
    expect(formatReleaseDate("", now)).toBe("");
    expect(formatReleaseDate("not a date", now)).toBe("");
  });
});
