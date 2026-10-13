// @vitest-environment jsdom
import { act, cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { OrderCenterPage } from "./OrderCenterPage";
import type { CommandRunner } from "./componentTypes";
import type { OrderHistoryPage, OrderHistorySummary } from "../types";
import { defaultStatus, railwatchStore } from "../store/railwatchStore";

beforeEach(() => railwatchStore.setState({ status: { ...defaultStatus } }));
afterEach(() => { cleanup(); vi.useRealTimers(); });

const summary: OrderHistorySummary = {
  intent_id: "intent-1", order_id: "E123", kind: "alternate", train_code: "D21",
  date: "2026-09-24", from_station: "北京", to_station: "上海", seat: "二等座",
  status: "active", official_status: "active", official_verified_at: 1790200000,
  updated_at: 1790200001, last_checked_at: 1790200000, observing: false, recovery_required: true,
};

test("reselects a deadline on the same unsubmitted intent and resumes explicitly", async () => {
  const item = { ...summary, order_id: null, status: "verification", official_status: null,
    review: { deadline_reselection: true, deadline_options: ["开车前20分钟", "开车前1小时"] } };
  const runCommand = vi.fn(async (command: string) => command === "orderHistory" ?
    { items: [item], next_cursor: null } : command === "orderDetail" ?
      { summary: item, events: [], history_complete: true } : undefined) as CommandRunner;
  render(<OrderCenterPage runCommand={runCommand} busy={null} />);
  await userEvent.click(await screen.findByRole("button", { name: "查看时间线" }));
  await userEvent.click(screen.getByRole("combobox", { name: "原候补截止兑现时间" }));
  await userEvent.click(await screen.findByText("开车前20分钟", { selector: ".ant-select-item-option-content" }));
  await userEvent.click(screen.getByRole("button", { name: "保存截止选项并继续原方案" }));
  expect(runCommand).toHaveBeenCalledWith("continueOrder", { intent_id: "intent-1", alternate_deadline: "开车前20分钟" });
});

test("history distinguishes official status, local observation, and incomplete events", async () => {
  const runCommand = vi.fn(async (command: string) => command === "orderHistory" ?
    { items: [summary], next_cursor: null } : command === "orderDetail" ?
      { summary, events: [], history_complete: false } : undefined) as CommandRunner;
  render(<OrderCenterPage runCommand={runCommand} busy={null} />);
  expect(await screen.findByText("D21", { selector: ".order-train" })).toBeTruthy();
  expect(screen.getAllByText(/./, { selector: ".order-station" }).map(node => node.textContent)).toEqual(["北京", "上海"]);
  expect(screen.getByRole("article", { name: "D21 北京至上海" })).toBeTruthy();
  expect(screen.getByText(/当前未观察/)).toBeTruthy();
  expect(screen.getByText(/当前未持续核对，可点击继续核对/)).toBeTruthy();
  await userEvent.click(screen.getByRole("button", { name: "查看时间线" }));
  expect(await screen.findByText(/历史事件不完整/)).toBeTruthy();
  expect(vi.mocked(runCommand).mock.calls.some(([command]) => command === "continueOrder")).toBe(false);
});

test("terminal history remains read only", async () => {
  const terminal = { ...summary, status: "fulfilled", official_status: "fulfilled" as const, recovery_required: false };
  const runCommand = vi.fn(async () => ({ items: [terminal], next_cursor: null })) as CommandRunner;
  render(<OrderCenterPage runCommand={runCommand} busy={null} />);
  expect((await screen.findAllByText(/购票成功/)).length).toBeGreaterThan(0);
  expect(screen.queryByRole("button", { name: /继续核对/ })).toBeNull();
});

test("multi-choice history exposes the saved set and stops only local observation", async () => {
  railwatchStore.setState({ status: { ...defaultStatus, monitoring: true } });
  const watching = { ...summary, observing: true, next_check_at: 1790200100, check_failures: 2,
    choices: [{ date: summary.date, train_code: "D21", from_station: "北京", to_station: "上海", seat: "二等座" },
      { date: "2026-09-25", train_code: "D22", from_station: "北京", to_station: "上海", seat: "二等座" }] };
  const runCommand = vi.fn(async (command: string) => command === "orderHistory"
    ? { items: [watching], next_cursor: null } : undefined) as CommandRunner;
  render(<OrderCenterPage runCommand={runCommand} busy={null} />);
  const choices = (await screen.findByText("已保存的候补组合（2个）")).closest("details")!;
  expect([...choices.querySelectorAll("li")].map(item => item.textContent))
    .toEqual(["9月24日 周四D21北京 → 上海二等座", "9月25日 周五D22北京 → 上海二等座"]);
  expect(screen.getByText(/暂未取得新证据，已放慢核对/)).toBeTruthy();
  await userEvent.click(screen.getByRole("button", { name: "停止本地核对" }));
  expect(runCommand).toHaveBeenCalledWith("stopMonitor");
  expect(vi.mocked(runCommand).mock.calls.map(call => call[0])).not.toContain("continueOrder");
});

test("groups orders by what they still need and folds finished ones into rows", async () => {
  const items = [
    { ...summary, intent_id: "done", train_code: "G1", status: "active", official_status: "fulfilled" as const, recovery_required: false },
    { ...summary, intent_id: "pay", train_code: "G2", status: "pending_payment", official_status: "pending_payment" as const, recovery_required: false },
    { ...summary, intent_id: "live", train_code: "G3" },
  ];
  const runCommand = vi.fn(async () => ({ items, next_cursor: null })) as CommandRunner;
  render(<OrderCenterPage runCommand={runCommand} busy={null} />);
  const attention = await screen.findByRole("region", { name: /需要你处理/ });
  expect(within(attention).getByText("候补待支付")).toBeTruthy();
  expect(within(attention).getByText(/完成预付款，支付后候补才生效/)).toBeTruthy();
  expect(within(screen.getByRole("region", { name: /进行中/ })).getByRole("article", { name: /^G3 / })).toBeTruthy();
  // The final official status outranks the stale local result.
  const ended = screen.getByRole("region", { name: /已结束/ });
  expect(within(ended).getByRole("article", { name: /^G1 / }).querySelector(".order-status-text")?.textContent).toBe("购票成功");
  expect(within(ended).getByText(/^官方确认/)).toBeTruthy();
  expect(within(ended).queryByRole("button", { name: "继续核对" })).toBeNull();
});

test("an empty filter result offers the way back to every order", async () => {
  const runCommand = vi.fn(async (_command: string, payload?: Record<string, unknown>) =>
    ({ items: payload?.status ? [] : [summary], next_cursor: null })) as CommandRunner;
  render(<OrderCenterPage runCommand={runCommand} busy={null} />);
  await screen.findByRole("article", { name: /^D21 / });
  await userEvent.click(screen.getByRole("combobox", { name: "按状态筛选" }));
  await userEvent.click(await screen.findByText("需要核验", { selector: ".ant-select-item-option-content" }));
  expect(await screen.findByText("没有「需要核验」的订单")).toBeTruthy();
  expect(runCommand).toHaveBeenCalledWith("orderHistory", { limit: 20, cursor: null, status: "verification" });
  await userEvent.click(screen.getByRole("button", { name: "查看全部订单" }));
  expect(await screen.findByRole("article", { name: /^D21 / })).toBeTruthy();
});

test("background refreshes keep the current list in place", async () => {
  let release: (value: OrderHistoryPage) => void = () => undefined;
  const runCommand = vi.fn(async () => ({ items: [summary], next_cursor: null })) as CommandRunner;
  render(<OrderCenterPage runCommand={runCommand} busy={null} />);
  await screen.findByRole("article", { name: /^D21 / });
  vi.mocked(runCommand).mockImplementationOnce((() => new Promise<OrderHistoryPage>(resolve => { release = resolve; })) as CommandRunner);
  act(() => railwatchStore.setState({ status: { ...defaultStatus, order: { status: "active", updated_at: 2 } } }));
  expect(runCommand).toHaveBeenCalledTimes(2);
  expect(screen.getByRole("article", { name: /^D21 / })).toBeTruthy();
  expect(screen.queryByText("正在读取订单记录…")).toBeNull();
  await act(async () => release({ items: [summary], next_cursor: null }));
});

test("active observation refreshes check results without a state transition and stops polling when monitoring ends", async () => {
  vi.useFakeTimers();
  railwatchStore.setState({ status: { ...defaultStatus, monitoring: true } });
  let latest = { ...summary, observing: true, last_check_status: "pending_payment" };
  const runCommand = vi.fn(async () => ({ items: [latest], next_cursor: null }));
  await act(async () => { render(<OrderCenterPage runCommand={runCommand as CommandRunner} busy={null} />); });
  expect(screen.getByText(/本地观察中/)).toBeTruthy();
  latest = { ...latest, last_checked_at: summary.last_checked_at! + 5, last_check_status: "unknown" };
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(runCommand).toHaveBeenCalledTimes(2);
  expect(screen.getByText("核对结果", { selector: "dt" }).nextElementSibling?.textContent).toBe("结果待核对");
  expect(screen.getByText(/候补已生效；正在持续核对兑现状态/)).toBeTruthy();
  latest = { ...latest, observing: false };
  await act(async () => { railwatchStore.setState({ status: { ...defaultStatus, monitoring: false } }); });
  expect(screen.getByText(/当前未观察/)).toBeTruthy();
  const calls = runCommand.mock.calls.length;
  await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
  expect(runCommand).toHaveBeenCalledTimes(calls);
});
