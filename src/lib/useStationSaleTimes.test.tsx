// @vitest-environment jsdom
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { railwatchApi } from "./railwatchApi";
import { useStationSaleTimes } from "./useStationSaleTimes";

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.useRealTimers(); });

test("focus after expiry refreshes, fresh focus reuses data, and unmount removes timers", async () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-09-27T09:00:00+08:00"));
  const start = Date.now();
  const command = vi.spyOn(railwatchApi, "command").mockImplementation(async () => ({
    station: "北京", status: "available", schedules: [], checked_at: Date.now() / 1000,
    expires_at: Date.now() / 1000 + 3600, retry_at: Date.now() / 1000 + 60, warning: null,
  }));
  const { unmount } = renderHook(() => useStationSaleTimes("北京"));
  await act(async () => {});
  await act(async () => { window.dispatchEvent(new Event("focus")); });
  expect(command).toHaveBeenCalledTimes(1);
  vi.setSystemTime(start + 3600_000);
  await act(async () => { window.dispatchEvent(new Event("focus")); });
  expect(command).toHaveBeenCalledTimes(2);
  unmount();
  vi.setSystemTime(start + 7200_000);
  window.dispatchEvent(new Event("focus"));
  expect(command).toHaveBeenCalledTimes(2);
  expect(vi.getTimerCount()).toBe(0);
});

test("a failed request retries after a minute without request flooding", async () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-09-27T09:00:00+08:00"));
  const command = vi.spyOn(railwatchApi, "command").mockRejectedValue(new Error("offline"));
  const { result } = renderHook(() => useStationSaleTimes("北京"));
  await act(async () => {});
  expect(result.current.error).toContain("暂不可用");
  await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
  expect(command).toHaveBeenCalledTimes(1);
  await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
  expect(command).toHaveBeenCalledTimes(2);
});
