// @vitest-environment jsdom
import { act, cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { OrderCenterPage } from "./OrderCenterPage";
import type { CommandRunner } from "./componentTypes";
import type { OrderHistorySummary } from "../types";
import { defaultStatus, railwatchStore } from "../store/railwatchStore";

beforeEach(() => railwatchStore.setState({ status: { ...defaultStatus } }));
afterEach(() => { cleanup(); vi.useRealTimers(); });

const summary: OrderHistorySummary = {
  intent_id: "intent-1", order_id: "E123", kind: "alternate", train_code: "D21",
  date: "2026-09-24", from_station: "北京", to_station: "上海", seat: "二等座",
  status: "active", official_status: "active", official_verified_at: 1790200000,
  updated_at: 1790200001, last_checked_at: 1790200000, observing: false, recovery_required: true,
};

test("history distinguishes official status, local observation, and incomplete events", async () => {
  const runCommand = vi.fn(async (command: string) => command === "orderHistory" ?
    { items: [summary], next_cursor: null } : command === "orderDetail" ?
      { summary, events: [], history_complete: false } : undefined) as CommandRunner;
  render(<OrderCenterPage runCommand={runCommand} busy={null} />);
  expect(await screen.findByText(/D21 · 北京 → 上海/)).toBeTruthy();
  expect(screen.getByText(/当前未观察/)).toBeTruthy();
  expect(screen.getByText(/当前不会周期性自动复查兑现状态/)).toBeTruthy();
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
  expect(screen.getByText("最近核对结果：结果待核对")).toBeTruthy();
  expect(screen.getByText(/候补已生效；当前不会周期性自动复查/)).toBeTruthy();
  latest = { ...latest, observing: false };
  await act(async () => { railwatchStore.setState({ status: { ...defaultStatus, monitoring: false } }); });
  expect(screen.getByText(/当前未观察/)).toBeTruthy();
  const calls = runCommand.mock.calls.length;
  await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
  expect(runCommand).toHaveBeenCalledTimes(calls);
});
