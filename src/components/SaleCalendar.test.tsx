// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import type { StationSaleTimes } from "../types";
import { railwatchApi } from "../lib/railwatchApi";
import { SaleCalendar } from "./SaleCalendar";

const now = Date.parse("2026-09-27T09:59:59+08:00");
function info(station = "北京", time = "10:00"): StationSaleTimes {
  return { station, status: "available", checked_at: now / 1000 - 10, expires_at: now / 1000 + 3590,
    retry_at: now / 1000 + 50, warning: null, source_url: "https://kyfw.12306.cn/index/view/infos/sale_time.html",
    schedules: [{ station_name: station, station_code: "BJP", sale_time: time, start_date: "2010-01-01", stop_date: "2099-12-31" }] };
}
const props = { station: "北京", tripDate: "2026-10-11", windowDays: 15, now };
beforeEach(() => { vi.spyOn(railwatchApi, "command").mockResolvedValue(info()); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("SaleCalendar", () => {
  test("shows official time, changes at release and date clicks only inspect", async () => {
    const { rerender } = render(<SaleCalendar {...props} />);
    await screen.findByText("10:00");
    expect(screen.getByText("00:00:01")).toBeTruthy();
    rerender(<SaleCalendar {...props} now={now + 1000} />);
    expect(screen.queryByText("00:00:01")).toBeNull();
    expect(screen.getByRole("button", { name: "2026-10-11 已到起售时间 当前行程" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "2026-10-12 未进入预售期" }));
    expect(within(screen.getByRole("complementary")).getByText("2026-09-28")).toBeTruthy();
    expect(vi.mocked(railwatchApi.command).mock.calls.map(call => call[0])).toEqual(["stationSaleTimes"]);
    fireEvent.click(screen.getByRole("button", { name: "返回行程日期" }));
    expect(screen.getByText("乘车日期 · 2026-10-11 · 当前行程")).toBeTruthy();
  });
  test("discards an old station response even when it finishes last", async () => {
    let resolveOld!: (value: StationSaleTimes) => void;
    vi.mocked(railwatchApi.command).mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }))
      .mockResolvedValueOnce(info("上海", "14:45"));
    const { rerender } = render(<SaleCalendar {...props} />);
    rerender(<SaleCalendar {...props} station="上海" />);
    await screen.findByText("14:45");
    await act(async () => resolveOld(info()));
    expect(screen.queryByText("10:00")).toBeNull();
    expect(screen.getByText("上海 · 出发站")).toBeTruthy();
  });
  test("expired information stops providing a countdown", async () => {
    vi.mocked(railwatchApi.command).mockResolvedValue({ ...info(), expires_at: now / 1000 + 0.5 });
    const { rerender } = render(<SaleCalendar {...props} />);
    await screen.findByText("10:00");
    rerender(<SaleCalendar {...props} now={now + 600} />);
    expect(screen.queryByText("10:00")).toBeNull();
    expect(screen.queryByText("00:00:01")).toBeNull();
    expect(screen.getByText("起售数据已过期，请刷新后核对。")).toBeTruthy();
  });
  test("preserves an out-of-window trip and refreshes without editing it", async () => {
    render(<SaleCalendar {...props} tripDate="2026-12-31" />);
    await screen.findByText("10:00");
    expect(screen.getByText("乘车日期 · 2026-12-31 · 当前行程")).toBeTruthy();
    const refresh = screen.getByRole("button", { name: "刷新起售时间" });
    // The time can render before Ant Design clears its internal loading state.
    await waitFor(() => expect(refresh.classList.contains("ant-btn-loading")).toBe(false));
    fireEvent.click(refresh);
    await waitFor(() => expect(railwatchApi.command).toHaveBeenLastCalledWith("stationSaleTimes", { station: "北京", force: true }));
  });
  test("renders failures with an official lookup and no invented sale time", async () => {
    vi.mocked(railwatchApi.command).mockRejectedValue(new Error("offline"));
    const open = vi.spyOn(railwatchApi, "openExternal").mockResolvedValue({ ok: true });
    render(<SaleCalendar {...props} />);
    await screen.findByText("起售时间暂不可用，请稍后刷新或前往官方核对。");
    fireEvent.click(screen.getByRole("button", { name: /前往官方核对/ }));
    expect(open).toHaveBeenCalledWith("https://kyfw.12306.cn/index/view/infos/sale_time.html");
    expect(screen.queryByText("10:00")).toBeNull();
  });
  test("empty station keeps the calendar usable without a request", () => {
    render(<SaleCalendar {...props} station="" tripDate="" />);
    expect(railwatchApi.command).not.toHaveBeenCalled();
    expect(screen.getByText("请先设置出发站")).toBeTruthy();
    expect(screen.getByRole("button", { name: "2026-10-11 时间待核对" })).toBeTruthy();
  });
  test("reports an external-link rejection from an older desktop bridge", async () => {
    vi.spyOn(railwatchApi, "openExternal").mockResolvedValue({ ok: false });
    render(<SaleCalendar {...props} />);
    await screen.findByText("10:00");
    fireEvent.click(screen.getByRole("button", { name: /前往官方核对/ }));
    expect(await screen.findByText("无法打开浏览器，请在 12306 中查询起售时间。")).toBeTruthy();
  });
  test("advances the visible dates at Beijing midnight without changing the trip", async () => {
    const before = Date.parse("2026-09-27T23:59:59+08:00");
    const { rerender } = render(<SaleCalendar {...props} now={before} />);
    await screen.findByText(/获取于/);
    rerender(<SaleCalendar {...props} now={before + 1000} />);
    expect(screen.queryByRole("button", { name: "2026-09-27 预售期内" })).toBeNull();
    expect(screen.getByRole("button", { name: "2026-09-28 预售期内" }).textContent).toContain("今天");
    expect(screen.getByText("乘车日期 · 2026-10-11 · 当前行程")).toBeTruthy();
  });
});
