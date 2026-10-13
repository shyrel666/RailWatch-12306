// @vitest-environment jsdom
import { act, cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { railwatchStore } from "../store/railwatchStore";
import { railwatchApi } from "../lib/railwatchApi";
import { RunReviews } from "./RunReviews";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });
beforeEach(() => railwatchStore.setState({ activePage: "运行复盘", pageSection: null }));

const segment = (id: string, label: string, duration_ms: number | null, start_ms: number | null = 0) =>
  ({ id, label, duration_ms, start_ms, source: duration_ms === null ? "未记录" : "本机观察" });

test("query statistics chart sample counts and revisit intervals and keep a data table", async () => {
  vi.spyOn(railwatchApi, "command").mockImplementation(async name => (name === "runReviews" ?
    { items: [{ run_id: "run-1", started_at: 1, target_at: null, conclusion: "已停止" }], next_cursor: null } :
    { run_id: "run-1", started_at: 1, target_at: null, conclusion: "已停止", segments: [], prediction: [], preparation_margin_ms: null,
      query_timings: { recorded_queries: 4, valid_queries: 3, window_limit: 200,
        phases: [{ id: "decision", label: "筛选车次与席别", samples: 3, median_ms: 24, p95_ms: 30 }],
        date_revisits: [{ date: "2026-10-10", samples: 2, median_ms: 12000, p95_ms: 14000 }] } }) as never);
  render(<RunReviews />);
  const region = await screen.findByRole("region", { name: "查询分阶段统计" });
  const phases = within(region).getByRole("figure", { name: "有效查询各阶段耗时" });
  expect(within(phases).getByText("筛选车次与席别")).toBeTruthy();
  expect(within(phases).getByText("3 个样本")).toBeTruthy();
  expect(within(phases).getByText("P95 30.0 ms")).toBeTruthy();
  expect(within(within(region).getByRole("figure", { name: "同一日期两次查询的实际间隔" })).getByText("10月10日 周六")).toBeTruthy();
  const table = within(region).getByRole("table", { name: "有效查询各阶段耗时" });
  expect(within(table).getByText("24.0 ms")).toBeTruthy();
  expect(within(table).getByText("30.0 ms")).toBeTruthy();
  expect(within(within(region).getByRole("table", { name: /同一日期两次查询/ })).getByText("12.00 秒")).toBeTruthy();
  expect(within(region).getByText(/少量样本仅供参考/)).toBeTruthy();
});

test("the newest run opens without a click and keeps an incomplete timeline explicit", async () => {
  const command = vi.spyOn(railwatchApi, "command").mockImplementation(async name => (name === "runReviews" ?
    { items: [{ run_id: "run-1", started_at: 1, target_at: null, conclusion: "未命中", trip: { from_station: "北京", to_station: "上海" } }], next_cursor: null } :
    { run_id: "run-1", started_at: 1, target_at: null, conclusion: "未命中", trip: { from_station: "北京", to_station: "上海" },
      segments: [segment("query", "查询往返", null)], prediction: [], preparation_margin_ms: null, slowest: null,
      note: "查询遥测可能已清理" }) as never);
  render(<RunReviews />);
  const detail = await screen.findByRole("article", { name: "复盘详情" });
  expect(within(detail).getByRole("heading", { name: "北京 → 上海" })).toBeTruthy();
  expect(within(detail).getByText("查询遥测可能已清理")).toBeTruthy();
  expect(within(detail).getByText(/未知分段不计入/)).toBeTruthy();
  expect(within(detail).getByText(/历史任务无法补算/)).toBeTruthy();
  expect(within(detail).getByText("即时任务无起售时刻")).toBeTruthy();
  expect(screen.getByRole("button", { name: "查看复盘" }).getAttribute("aria-pressed")).toBe("true");
  expect(screen.queryByText("查看复盘")).toBeNull();
  expect(screen.queryByText(/记录即时与定时监控的执行阶段/)).toBeNull();
  expect(command.mock.calls.map(call => call[0])).toEqual(["runReviews", "runReview"]);
});

test("order steps explain the slow portion without adding them to the overall total", async () => {
  vi.spyOn(railwatchApi, "command").mockImplementation(async name => (name === "runReviews" ?
    { items: [{ run_id: "run-1", started_at: 1, target_at: null, conclusion: "待支付" }], next_cursor: null } :
    { run_id: "run-1", started_at: 1, target_at: null, conclusion: "待支付", segments: [segment("readback", "下单页与核对", 7000)],
      prediction: [], preparation_margin_ms: null, slowest: "下单页与核对", note: "本机观察时间",
      order_timings: [{ kind: "regular", segments: [segment("page_load", "打开并等待下单页", 6000),
        segment("passengers", "选择乘车人", 1000, 6000)] }] }) as never);
  render(<RunReviews />);
  const breakdown = await screen.findByRole("region", { name: "下单分步耗时" });
  const slowest = within(breakdown).getByText("打开并等待下单页").closest("li")!;
  expect(slowest.className).toContain("is-peak");
  expect(within(slowest).getByText("最慢")).toBeTruthy();
  expect(within(breakdown).getByText("6.00 秒")).toBeTruthy();
  expect(within(breakdown).getByText(/不重复计入总耗时/)).toBeTruthy();
  expect(screen.getAllByText(/已知分段合计 7.00 秒/)).toHaveLength(2);
  expect(screen.queryByText(/已知分段合计 14.00 秒/)).toBeNull();
});

test.each(["card", "route", "time", "Enter", "Space"])("opening a run with %s selects its detail exactly once", async (target) => {
  const runs = [
    { run_id: "run-1", started_at: 1, target_at: null, conclusion: "已停止", trip: { from_station: "北京", to_station: "上海" } },
    { run_id: "run-2", started_at: 1, target_at: 2, conclusion: "候补已生效", trip: { from_station: "广州", to_station: "长沙" } },
  ];
  const command = vi.spyOn(railwatchApi, "command").mockImplementation(async (name, payload) => {
    if (name === "runReviews") return { items: runs, next_cursor: null } as never;
    const run = runs.find(item => item.run_id === payload?.run_id)!;
    return { ...run, segments: [segment("wake", "唤醒迟到", 90)], prediction: [], slowest: "唤醒迟到", note: "",
      preparation_margin_ms: run.run_id === "run-2" ? 8400 : null } as never;
  });
  render(<RunReviews />);
  await screen.findByRole("heading", { name: "北京 → 上海" });
  const cards = within(screen.getByRole("navigation", { name: "任务列表" })).getAllByRole("button", { name: "查看复盘" });
  expect(cards[1].tagName).toBe("BUTTON");
  expect(within(cards[1]).queryByText("查看复盘")).toBeNull();
  command.mockClear();
  const user = userEvent.setup();
  if (target === "Enter" || target === "Space") {
    cards[1].focus();
    await user.keyboard(target === "Enter" ? "{Enter}" : " ");
  } else {
    await user.click(target === "route" ? within(cards[1]).getByText("广州 → 长沙 · 定时")
      : target === "time" ? cards[1].querySelector("time")! : cards[1]);
  }
  expect(await screen.findByRole("heading", { name: "广州 → 长沙" })).toBeTruthy();
  expect(cards.map(card => card.getAttribute("aria-pressed"))).toEqual(["false", "true"]);
  expect(command).toHaveBeenCalledTimes(1);
  expect(command).toHaveBeenCalledWith("runReview", { run_id: "run-2" });
  expect(screen.getByText("8.40 秒")).toBeTruthy();
  expect(screen.getByText("不足 10 秒，建议提前启动")).toBeTruthy();
});

test("a slow response for an earlier selection cannot replace the run chosen afterwards", async () => {
  const runs = [
    { run_id: "run-1", started_at: 1, target_at: null, conclusion: "已停止", trip: { from_station: "北京", to_station: "上海" } },
    { run_id: "run-2", started_at: 1, target_at: null, conclusion: "已停止", trip: { from_station: "广州", to_station: "长沙" } },
  ];
  let finishFirst: (() => void) | null = null;
  vi.spyOn(railwatchApi, "command").mockImplementation(async (name, payload) => {
    if (name === "runReviews") return { items: runs, next_cursor: null } as never;
    const run = runs.find(item => item.run_id === payload?.run_id)!;
    const detail = { ...run, segments: [], prediction: [], slowest: null, note: "", preparation_margin_ms: null };
    // The automatically opened newest run answers only after the user picks another one.
    if (run.run_id === "run-1") await new Promise<void>(resolve => { finishFirst = resolve; });
    return detail as never;
  });
  render(<RunReviews />);
  const cards = await within(await screen.findByRole("navigation", { name: "任务列表" })).findAllByRole("button", { name: "查看复盘" });
  await userEvent.click(cards[1]);
  expect(await screen.findByRole("heading", { name: "广州 → 长沙" })).toBeTruthy();
  await act(async () => finishFirst?.());
  expect(screen.getByRole("heading", { name: "广州 → 长沙" })).toBeTruthy();
  expect(screen.queryByRole("heading", { name: "北京 → 上海" })).toBeNull();
  expect(cards.map(card => card.getAttribute("aria-pressed"))).toEqual(["false", "true"]);
});

test("runs without a recorded route have no dangling arrow and an empty history points to monitoring", async () => {
  const command = vi.spyOn(railwatchApi, "command").mockImplementation(async name => (name === "runReviews"
    ? { items: [{ run_id: "old-run", started_at: 1, conclusion: "需要核验" }], next_cursor: null }
    : { run_id: "old-run", started_at: 1, target_at: null, conclusion: "需要核验", segments: [], prediction: [],
      preparation_margin_ms: null, note: "" }) as never);
  render(<RunReviews />);
  expect(await screen.findByText("路线未记录 · 即时")).toBeTruthy();
  await screen.findByRole("article", { name: "复盘详情" });
  expect(screen.queryByText(/→/)).toBeNull();
  cleanup();
  command.mockImplementation(async () => ({ items: [], next_cursor: null }) as never);
  render(<RunReviews />);
  expect(await screen.findByText("暂无任务复盘记录")).toBeTruthy();
  await userEvent.click(screen.getByRole("button", { name: "前往购票监控" }));
  expect(railwatchStore.getState().activePage).toBe("购票监控");
});
