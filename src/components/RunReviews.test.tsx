// @vitest-environment jsdom
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { railwatchStore } from "../store/railwatchStore";
import { railwatchApi } from "../lib/railwatchApi";
import { RunReviews } from "./RunReviews";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });
beforeEach(() => railwatchStore.setState({ pageSection: null }));
test("shows the run and incomplete timeline without browser actions", async () => {
  const command = vi.spyOn(railwatchApi, "command").mockImplementation(async name => (name === "runReviews" ?
    { items: [{ run_id: "run-1", started_at: 1, target_at: null, conclusion: "未命中", trip: { from_station: "北京", to_station: "上海" } }], next_cursor: null } :
    { run_id: "run-1", conclusion: "未命中", segments: [{ id: "query", label: "查询往返", duration_ms: null, source: "未记录" }], prediction: [], preparation_margin_ms: null, slowest: null,
      note: "查询遥测可能已清理" }) as never);
  render(<RunReviews />);
  const toggle = screen.getByRole("button", { name: /运行复盘/ });
  expect(toggle.getAttribute("aria-expanded")).toBe("false");
  expect(screen.queryByRole("button", { name: "查看复盘" })).toBeNull();
  await userEvent.click(toggle);
  expect(toggle.getAttribute("aria-expanded")).toBe("true");
  await userEvent.click(await screen.findByRole("button", { name: "查看复盘" }));
  expect(await screen.findByText("查询遥测可能已清理")).toBeTruthy();
  expect(screen.getByText(/未知分段不计入/)).toBeTruthy();
  expect(screen.getByText(/历史任务无法补算/)).toBeTruthy();
  expect(command.mock.calls.map(call => call[0])).toEqual(["runReviews", "runReview"]);
  await userEvent.click(toggle);
  expect(screen.queryByRole("article", { name: "复盘详情" })).toBeNull();
  expect(screen.queryByRole("button", { name: "刷新复盘" })).toBeNull();
});

test("order steps explain the slow portion without adding them to the overall total", async () => {
  railwatchStore.setState({ pageSection: "order-run-reviews" });
  const segment = (id: string, label: string, duration_ms: number, start_ms = 0) =>
    ({ id, label, duration_ms, start_ms, source: "本机观察" });
  vi.spyOn(railwatchApi, "command").mockImplementation(async name => (name === "runReviews" ?
    { items: [{ run_id: "run-1", started_at: 1, target_at: null, conclusion: "待支付" }], next_cursor: null } :
    { run_id: "run-1", conclusion: "待支付", segments: [segment("readback", "下单页与核对", 7000)],
      prediction: [], preparation_margin_ms: null, slowest: "下单页与核对", note: "本机观察时间",
      order_timings: [{ kind: "regular", segments: [segment("page_load", "打开并等待下单页", 6000),
        segment("passengers", "选择乘车人", 1000, 6000)] }] }) as never);
  render(<RunReviews />);
  await userEvent.click(await screen.findByRole("button", { name: "查看复盘" }));
  const breakdown = await screen.findByRole("region", { name: "下单分步耗时" });
  expect(within(breakdown).getByText("打开并等待下单页")).toBeTruthy();
  expect(within(breakdown).getByText("6.00 秒")).toBeTruthy();
  expect(within(breakdown).getByText(/不重复计入总耗时/)).toBeTruthy();
  expect(screen.getAllByText(/已知分段合计 7.00 秒/)).toHaveLength(2);
  expect(screen.queryByText(/已知分段合计 14.00 秒/)).toBeNull();
});

test("the review shortcut expands the section and missing routes have no dangling arrow", async () => {
  railwatchStore.setState({ pageSection: "order-run-reviews" });
  vi.spyOn(railwatchApi, "command").mockResolvedValue({ items: [
    { run_id: "old-run", started_at: 1, conclusion: "需要核验" },
  ], next_cursor: null });
  render(<RunReviews />);
  expect(screen.getByRole("button", { name: /运行复盘/ }).getAttribute("aria-expanded")).toBe("true");
  expect(await screen.findByText(/路线未记录 · 需要核验/)).toBeTruthy();
  expect(screen.queryByText(/→/)).toBeNull();
});
