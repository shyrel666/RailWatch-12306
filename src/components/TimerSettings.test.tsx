// @vitest-environment jsdom
import { useState } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { railwatchApi } from "../lib/railwatchApi";
import { defaultConfig } from "../store/railwatchStore";
import type { RailWatchConfig, StationSaleTimes } from "../types";
import { TimerSettings } from "./TimerSettings";

const now = Date.parse("2026-09-27T09:00:00+08:00");
const info = (station = "北京"): StationSaleTimes => ({
  station, status: "available", checked_at: now / 1000 - 10, expires_at: now / 1000 + 3600,
  retry_at: now / 1000 + 60, warning: null, source_url: "https://kyfw.12306.cn/index/view/infos/sale_time.html",
  schedules: [{ station_name: station, station_code: "BJP", sale_time: "10:00",
    start_date: "2010-01-01", stop_date: "2099-12-31" }],
});
const config = { ...defaultConfig, from_station_cn: "北京", date: "2026-10-11", timer_enabled: true, sale_at: "" };
beforeEach(() => {
  vi.spyOn(Date, "now").mockReturnValue(now);
  vi.spyOn(railwatchApi, "command").mockResolvedValue(info());
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

function EditableForm({ initial = config }: { initial?: RailWatchConfig }) {
  const [value, setValue] = useState(initial);
  return <TimerSettings config={value} update={patch => setValue(previous => ({ ...previous, ...patch }))} />;
}

test("a released trip can switch to immediate mode without filling a time or leaving disabled actions", async () => {
  render(<EditableForm initial={{ ...config, date: "2026-10-07" }} />);
  const section = screen.getByRole("heading", { name: "定时启动" }).closest("details")!;
  expect(section.open).toBe(false);
  fireEvent.click(screen.getByRole("heading", { name: "定时启动" }));
  expect(section.open).toBe(true);
  await screen.findByText("已进入预售期，建议立即开始监控，无需填写定时时间。");
  fireEvent.click(screen.getByRole("button", { name: "改为立即开始" }));
  expect((screen.getByRole("radio", { name: "立即开始" }) as HTMLInputElement).checked).toBe(true);
  expect(screen.queryByLabelText("定时启动时间")).toBeNull();
  expect(screen.queryByText(/请选择开始时间/)).toBeNull();
  expect(screen.queryByRole("button", { name: "设为起售时间" })).toBeNull();
  expect(screen.getByText("立即开始 · 点击开始监控后直接查询")).toBeTruthy();
});

test("choosing scheduled mode fills a future release, but preserves a custom time across mode switches", async () => {
  render(<EditableForm initial={{ ...config, timer_enabled: false }} />);
  fireEvent.click(screen.getByText("定时启动", { selector: "h2" }));
  await screen.findByRole("button", { name: "设为起售时间" });
  expect(screen.queryByLabelText("定时启动时间")).toBeNull();
  fireEvent.click(screen.getByRole("radio", { name: "定时开始" }));
  expect((screen.getByLabelText("定时启动时间") as HTMLInputElement).value).toBe("2026-09-27T10:00");
  expect(screen.getByText("已使用当前行程起售时间")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("定时启动时间"), { target: { value: "2026-09-28T11:30" } });
  fireEvent.click(screen.getByRole("radio", { name: "立即开始" }));
  fireEvent.click(screen.getByRole("radio", { name: "定时开始" }));
  expect((screen.getByLabelText("定时启动时间") as HTMLInputElement).value).toBe("2026-09-28T11:30");
});

test("failed lookup still permits manual scheduling", async () => {
  vi.mocked(railwatchApi.command).mockRejectedValue(new Error("offline"));
  render(<EditableForm />);
  await screen.findByText("起售时间暂不可用，请稍后刷新或前往官方核对。");
  expect(screen.queryByRole("button", { name: "设为起售时间" })).toBeNull();
  fireEvent.change(screen.getByLabelText("定时启动时间"), { target: { value: "2026-09-28T11:30" } });
  expect(screen.getByText("定时开始 · 2026-09-28 11:30:00（北京时间）")).toBeTruthy();
});

test("a changed trip explains how to update an earlier applied release time", async () => {
  render(<TimerSettings config={{ ...config, date: "2026-10-12", sale_time_source: "12306",
    sale_at: "2026-09-27T10:00:00+08:00" }} update={vi.fn()} />);
  await screen.findByText("当前设置与此行程的起售时间不同，请点击“设为起售时间”更新，或手动修改。");
  expect(screen.getByRole("button", { name: "设为起售时间" })).toBeTruthy();
});

test("applying the official time enables the timer, keeps Beijing time and still allows manual edits", async () => {
  const update = vi.fn();
  function Form() {
    const [value, setValue] = useState({ ...config, timer_enabled: false });
    return <TimerSettings config={value} update={patch => {
      update(patch); setValue(previous => ({ ...previous, ...patch }));
    }} />;
  }
  render(<Form />);
  fireEvent.click(screen.getByText("定时启动", { selector: "h2" }));
  const apply = await screen.findByRole("button", { name: "设为起售时间" });
  expect(update).not.toHaveBeenCalled();
  fireEvent.click(apply);
  expect(update).toHaveBeenLastCalledWith({ timer_enabled: true, sale_at: "2026-09-27T10:00:00+08:00",
    target_time: "10:00:00", sale_time_source: "12306", sale_time_checked_at: "2026-09-27T00:59:50.000Z" });
  expect(screen.getByText("定时开始 · 2026-09-27 10:00:00（北京时间）")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("定时启动时间"), { target: { value: "2026-09-28T11:30" } });
  expect(update).toHaveBeenLastCalledWith(expect.objectContaining({
    sale_at: "2026-09-28T11:30+08:00", sale_time_source: "manual",
  }));
  fireEvent.change(screen.getByLabelText("定时启动时间"), { target: { value: "" } });
  expect(screen.getByText("定时开始 · 请选择开始时间")).toBeTruthy();
  expect(screen.queryByText(/旧版/)).toBeNull();
  expect(vi.mocked(railwatchApi.command).mock.calls.every(([command]) => command === "stationSaleTimes")).toBe(true);
});

test.each([
  ["expired data", { ...info(), expires_at: now / 1000 - 1 }],
  ["ambiguous times", { ...info(), schedules: [...info().schedules, { ...info().schedules[0], sale_time: "11:00" }] }],
  ["unavailable data", { ...info(), status: "unavailable", schedules: [] }],
])("does not apply %s or overwrite the manual time", async (_name, response) => {
  vi.mocked(railwatchApi.command).mockResolvedValue(response);
  const update = vi.fn();
  render(<TimerSettings config={{ ...config, sale_at: "2026-09-28T12:00:00+08:00" }} update={update} />);
  await screen.findByText("暂未查到明确起售时间。可刷新重试，或按官方公告手动设置。");
  expect(screen.queryByRole("button", { name: "设为起售时间" })).toBeNull();
  expect(update).not.toHaveBeenCalled();
  expect((screen.getByLabelText("定时启动时间") as HTMLInputElement).value).toBe("2026-09-28T12:00");
});

test("already released trips suggest starting directly and past manual timers report their behavior", async () => {
  render(<TimerSettings config={{ ...config, date: "2026-10-10", sale_at: "2026-09-26T10:00:00+08:00" }} update={vi.fn()} />);
  await screen.findByText("已进入预售期，建议立即开始监控，无需填写定时时间。");
  expect(screen.queryByRole("button", { name: "设为起售时间" })).toBeNull();
  expect(screen.getByText("指定时间已到 · 点击开始监控后直接查询")).toBeTruthy();
});

test("changing the station cannot apply a late response for the previous station", async () => {
  let resolveOld!: (value: StationSaleTimes) => void;
  vi.mocked(railwatchApi.command).mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }))
    .mockResolvedValueOnce({ ...info("上海"), schedules: [{ ...info("上海").schedules[0], sale_time: "14:00" }] });
  const update = vi.fn();
  const { rerender } = render(<TimerSettings config={config} update={update} />);
  rerender(<TimerSettings config={{ ...config, from_station_cn: "上海" }} update={update} />);
  await screen.findByText("预计 2026-09-27 14:00:00 起售（北京时间）。");
  await act(async () => resolveOld(info()));
  fireEvent.click(screen.getByRole("button", { name: "设为起售时间" }));
  expect(update).toHaveBeenLastCalledWith(expect.objectContaining({ sale_at: "2026-09-27T14:00:00+08:00" }));
});

test("changing the trip date uses the current presale policy, and refreshing only reads data", async () => {
  const update = vi.fn<(patch: Partial<RailWatchConfig>) => void>();
  const { rerender } = render(<TimerSettings config={config} update={update} />);
  await screen.findByText("预计 2026-09-27 10:00:00 起售（北京时间）。");
  rerender(<TimerSettings config={{ ...config, date: "2026-10-12" }} windowDays={10} update={update} />);
  fireEvent.click(screen.getByRole("button", { name: "设为起售时间" }));
  expect(update).toHaveBeenLastCalledWith(expect.objectContaining({ sale_at: "2026-10-03T10:00:00+08:00" }));
  update.mockClear();
  fireEvent.click(screen.getByRole("button", { name: "刷新起售时间" }));
  await waitFor(() => expect(railwatchApi.command).toHaveBeenLastCalledWith("stationSaleTimes", { station: "北京", force: true }));
  expect(update).not.toHaveBeenCalled();
});
