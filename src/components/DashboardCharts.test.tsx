// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { railwatchApi } from "../lib/railwatchApi";
import { defaultStatus, railwatchStore } from "../store/railwatchStore";
import type { QueryPulse, RunReviewSummary } from "../types";
import { QueryPulseCard, RunHistoryCard } from "./DashboardCharts";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
beforeEach(() => railwatchStore.setState({ activePage: "仪表盘", pageSection: null }));

const now = Date.parse("2026-10-11T12:00:00+08:00");
const pulse = (overrides: Partial<QueryPulse> = {}): QueryPulse => ({
  run_id: "run-1",
  started_at: now / 1000 - 600,
  target_at: null,
  trip: { from_station: "北京", to_station: "上海" },
  recorded: 248,
  active: false,
  items: [
    { at: now / 1000 - 30, date: "2026-10-12", status: "ok", duration_ms: 1000, hit: false },
    { at: now / 1000 - 20, date: "2026-10-12", status: "timeout", duration_ms: 6000, hit: false },
    { at: now / 1000 - 10, date: "2026-10-13", status: "ok", duration_ms: 2000, hit: true },
    { at: now / 1000 - 5, date: "", status: "ok", duration_ms: null, hit: null },
  ],
  ...overrides,
});
const kpi = (card: HTMLElement, label: string) => within(card).getByText(label, { selector: "dt" }).parentElement?.textContent;

test("the pulse shows the last run's queries with their outcomes and a data table", async () => {
  const command = vi.spyOn(railwatchApi, "command").mockResolvedValue(pulse() as never);
  render(<QueryPulseCard status={defaultStatus} loops={0} now={now} />);
  const card = screen.getByRole("region", { name: "查询脉搏" });
  expect(await within(card).findByText(/上次运行 10\/11 11:50 · 北京→上海/)).toBeTruthy();
  expect(command).toHaveBeenCalledWith("queryPulse", { limit: 60 });
  expect(kpi(card, "查询次数")).toContain("248");
  expect(kpi(card, "中位耗时")).toContain("2.0 秒");
  expect(kpi(card, "有效查询")).toContain("75%");
  expect(kpi(card, "命中")).toContain("1");
  const rows = within(within(card).getByRole("table", { name: "最近 4 次查询" })).getAllByRole("row").slice(1);
  expect(rows.map((row) => row.textContent)).toEqual([
    "11:59:302026-10-121.0 秒有结果",
    "11:59:402026-10-126.0 秒查询超时",
    "11:59:502026-10-132.0 秒命中余票",
    "11:59:55未记录未记录有结果",
  ]);
  expect(card.querySelectorAll(".pulse-slot.hit")).toHaveLength(1);
  expect(card.querySelectorAll(".pulse-slot.miss")).toHaveLength(1);
  expect(within(card).queryByRole("button", { name: "运行复盘" })).toBeNull();
});

test("a running task counts live loops and never invents a next query deadline", async () => {
  vi.spyOn(railwatchApi, "command").mockResolvedValue(pulse({ active: true, recorded: 17 }) as never);
  const status = { ...defaultStatus, monitoring: true, task: { run_id: "run-1", status: "backoff", next_query_at: now / 1000 + 7 } };
  const { rerender } = render(<QueryPulseCard status={status} loops={18} now={now} />);
  const card = screen.getByRole("region", { name: "查询脉搏" });
  expect(within(card).getByRole("status").textContent).toBe("下次查询 7 秒");
  await within(card).findByRole("table", { name: "最近 4 次查询" });
  expect(kpi(card, "查询次数")).toContain("18");
  rerender(<QueryPulseCard status={{ ...status, task: { run_id: "run-1", status: "waiting" } }} loops={18} now={now} />);
  expect(within(card).getByRole("status").textContent).toBe("等待定时启动");
  rerender(<QueryPulseCard status={{ ...status, task: undefined }} loops={18} now={now} />);
  expect(within(card).getByRole("status").textContent).toBe("监控中");
});

test("a new run never shows the previous run's queries as live", async () => {
  vi.spyOn(railwatchApi, "command").mockResolvedValue(pulse() as never);
  const status = { ...defaultStatus, monitoring: true, task: { run_id: "run-2", status: "preparing" } };
  render(<QueryPulseCard status={status} loops={0} now={now} />);
  const card = screen.getByRole("region", { name: "查询脉搏" });
  expect(await within(card).findByText("等待第一次查询完成")).toBeTruthy();
  expect(kpi(card, "查询次数")).toContain("0");
  expect(card.querySelectorAll(".pulse-slot")).toHaveLength(0);
});

test("a finished query refreshes the pulse", async () => {
  const command = vi.spyOn(railwatchApi, "command").mockResolvedValue(pulse() as never);
  const status = { ...defaultStatus, monitoring: true };
  const { rerender } = render(<QueryPulseCard status={status} loops={1} now={now} />);
  await waitFor(() => expect(command).toHaveBeenCalledTimes(1));
  rerender(<QueryPulseCard status={status} loops={2} now={now} />);
  await waitFor(() => expect(command).toHaveBeenCalledTimes(2), { timeout: 2000 });
});

test("without queries the pulse invites a first run instead of showing zeros", async () => {
  vi.spyOn(railwatchApi, "command").mockResolvedValue(pulse({ run_id: null, started_at: null, recorded: 0, items: [] }) as never);
  render(<QueryPulseCard status={defaultStatus} loops={0} now={now} />);
  const card = screen.getByRole("region", { name: "查询脉搏" });
  expect(await within(card).findByText("还没有查询记录")).toBeTruthy();
  expect(within(card).queryByText("查询次数")).toBeNull();
  await userEvent.click(within(card).getByRole("button", { name: "前往购票监控" }));
  expect(railwatchStore.getState().activePage).toBe("购票监控");
});

test("an unreadable pulse says so", async () => {
  vi.spyOn(railwatchApi, "command").mockRejectedValue(new Error("offline"));
  render(<QueryPulseCard status={defaultStatus} loops={0} now={now} />);
  expect(await screen.findByText("查询记录暂时无法读取")).toBeTruthy();
});

test("run history buckets the last 14 days by outcome across pages", async () => {
  const today = Date.now() / 1000;
  const run = (started_at: number, conclusion: string): RunReviewSummary => ({ run_id: `${started_at}-${conclusion}`, started_at, target_at: null, conclusion });
  const command = vi.spyOn(railwatchApi, "command").mockImplementation(async (_name, payload) =>
    (payload?.cursor === "older"
      ? { items: [run(today - 2 * 86_400, "待支付"), run(today - 20 * 86_400, "已停止")], next_cursor: "oldest" }
      : { items: [run(today, "进行中"), run(today, "购票成功"), run(today, "已停止")], next_cursor: "older" }) as never);
  render(<RunHistoryCard monitoring={false} now={Date.now()} />);
  const card = screen.getByRole("region", { name: "近 14 天运行" });
  await within(card).findByText("运行次数");
  expect(command).toHaveBeenCalledTimes(2);
  expect(command).toHaveBeenLastCalledWith("runReviews", { limit: 50, cursor: "older" });
  expect(kpi(card, "运行次数")).toContain("4");
  expect(kpi(card, "成功")).toContain("1");
  const rows = within(within(card).getByRole("table", { name: "近 14 天每日运行结论" })).getAllByRole("row");
  expect(rows).toHaveLength(15);
  expect(Array.from(rows.at(-1)!.querySelectorAll("td"), (cell) => cell.textContent)).toEqual(["1", "0", "1", "1"]);
  expect(Array.from(rows.at(-3)!.querySelectorAll("td"), (cell) => cell.textContent)).toEqual(["0", "1", "0", "0"]);
  await userEvent.click(within(card).getByRole("button", { name: "运行复盘" }));
  expect(railwatchStore.getState().activePage).toBe("运行复盘");
});

test("run history explains an empty or unreadable window", async () => {
  const command = vi.spyOn(railwatchApi, "command").mockResolvedValue({ items: [], next_cursor: null } as never);
  render(<RunHistoryCard monitoring={false} now={Date.now()} />);
  expect(await screen.findByText("近 14 天没有运行记录")).toBeTruthy();
  expect(screen.queryByText("运行次数")).toBeNull();
  cleanup();
  command.mockRejectedValue(new Error("offline"));
  render(<RunHistoryCard monitoring={false} now={Date.now()} />);
  expect(await screen.findByText("运行记录暂时无法读取")).toBeTruthy();
});
