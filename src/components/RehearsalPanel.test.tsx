// @vitest-environment jsdom
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { createRailWatchStore, defaultConfig, railwatchStore, tripFingerprint } from "../store/railwatchStore";
import { RehearsalPanel } from "./RehearsalPanel";
import { railwatchApi } from "../lib/railwatchApi";
import type { RehearsalReport } from "../lib/rehearsal";

const report: RehearsalReport = { schema_version: 1, rehearsal_id: "one", trigger: "manual", started_at: 1, finished_at: 2,
  verdict: "blocked", trip: { from_station: "北京", to_station: "上海", date: "2026-10-12", sale_at: "" }, measurements: {},
  checks: [{ id: "login", title: "登录会话", critical: true, status: "fail", summary: "登录失效", duration_ms: 30,
    fix: { page: "系统设置", section: "settings-login", label: "重新登录" } }] };
beforeEach(() => {
  const initial = createRailWatchStore().getState();
  // Keep action closures bound to the singleton used by the component.
  railwatchStore.setState({ config: initial.config, status: initial.status, rehearsal: initial.rehearsal,
    activePage: initial.activePage, pageSection: null });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

test("a manual run opens the dialog, checks light up, cancellation stays available, and fixes navigate", async () => {
  const command = vi.spyOn(railwatchApi, "command").mockResolvedValue({ cancelled: true });
  railwatchStore.getState().prepareRehearsal(defaultConfig);
  railwatchStore.getState().applyRehearsalStarted({ rehearsal_id: "one", trigger: "manual", checks: [{ id: "login", title: "登录会话", critical: true }] });
  render(<RehearsalPanel busy="rehearse" runCommand={vi.fn()} />);
  const dialog = await screen.findByRole("dialog");
  expect(within(dialog).getByText("待检查")).toBeTruthy();
  expect(screen.getByText(/已完成 0\/1 项检查/)).toBeTruthy();
  await userEvent.click(within(dialog).getByRole("button", { name: "取消彩排" }));
  expect(command).toHaveBeenCalledWith("cancelRehearsal");
  act(() => railwatchStore.getState().applyRehearsalStep({ rehearsal_id: "one", check: report.checks[0] }));
  expect(within(dialog).getByText("登录失效")).toBeTruthy();
  act(() => railwatchStore.getState().applyRehearsalFinished({ report }));
  await userEvent.click(within(dialog).getByRole("button", { name: "重新登录" }));
  expect(railwatchStore.getState().pageSection).toBe("settings-login");
});

test("a task-triggered run stays in the panel until the user opens the dialog", async () => {
  railwatchStore.getState().applyRehearsalStarted({ rehearsal_id: "task", trigger: "task", checks: [{ id: "login", title: "登录会话", critical: true }] });
  render(<RehearsalPanel busy={null} runCommand={vi.fn()} />);
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(screen.getByText(/随定时任务执行/)).toBeTruthy();
  await userEvent.click(screen.getByRole("button", { name: "查看进度" }));
  expect(within(await screen.findByRole("dialog")).getByText("待检查")).toBeTruthy();
});

test("a finished report shows a summary, and the dialog can be reopened and closed", async () => {
  railwatchStore.setState({ rehearsal: { ...railwatchStore.getState().rehearsal, report, fingerprint: tripFingerprint(defaultConfig) } });
  render(<RehearsalPanel busy={null} runCommand={vi.fn()} />);
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(screen.getByText(/1 会失败/)).toBeTruthy();
  await userEvent.click(screen.getByRole("button", { name: "查看结果" }));
  const dialog = await screen.findByRole("dialog");
  expect(within(dialog).getByText("登录失效")).toBeTruthy();
  await userEvent.click(within(dialog).getByRole("button", { name: /关\s*闭/ }));
  // jsdom never finishes antd's leave motion, so the closing class is the observable signal.
  await waitFor(() => expect(document.querySelector(".rehearsal-dialog")?.classList.contains("ant-zoom-leave")).toBe(true));
  expect(railwatchStore.getState().rehearsal.report).toEqual(report);
});

test("edited config makes results stale and cannot silently apply the old official time", async () => {
  railwatchStore.setState({ rehearsal: { ...railwatchStore.getState().rehearsal, report: { ...report, checks: [{ ...report.checks[0],
    fix: { page: "行程设置", section: "trip-timer", label: "改为官方时刻", sale_at: "2026-09-28T15:00:00+08:00" } }] }, fingerprint: tripFingerprint(defaultConfig) } });
  railwatchStore.getState().setConfig({ date: "2026-10-13" });
  render(<RehearsalPanel busy={null} runCommand={vi.fn()} />);
  expect(screen.getByText(/彩排结果已过期/)).toBeTruthy();
  await userEvent.click(screen.getByRole("button", { name: "查看结果" }));
  await userEvent.click(await screen.findByRole("button", { name: "核对定时" }));
  expect(railwatchStore.getState().config.sale_at).toBe("");
});

test("applying the official time writes the same fields as the timer settings", async () => {
  railwatchStore.setState({ rehearsal: { ...railwatchStore.getState().rehearsal, report: { ...report, checks: [{ ...report.checks[0],
    fix: { page: "行程设置", section: "trip-timer", label: "改为官方时刻", sale_at: "2026-09-28T15:00:00+08:00", checked_at: 1790000000 } }] },
    fingerprint: tripFingerprint(defaultConfig) } });
  render(<RehearsalPanel busy={null} runCommand={vi.fn()} />);
  await userEvent.click(screen.getByRole("button", { name: "查看结果" }));
  await userEvent.click(await screen.findByRole("button", { name: "改为官方时刻" }));
  expect(railwatchStore.getState().config).toMatchObject({ sale_at: "2026-09-28T15:00:00+08:00", timer_enabled: true,
    target_time: "15:00:00", sale_time_source: "12306", sale_time_checked_at: new Date(1790000000 * 1000).toISOString() });
});

test("notifications are opt-in and the request freezes config", async () => {
  const command = vi.fn(async () => undefined);
  render(<RehearsalPanel busy={null} runCommand={command} />);
  await userEvent.click(screen.getByRole("button", { name: "开始彩排" }));
  expect(command).toHaveBeenCalledWith("rehearse", { config: defaultConfig, options: { send_test_notification: false } });
});

test("clearing removes stored results from the UI but preserves the cooldown and rejects late history", async () => {
  const recent = { ...report, started_at: Date.now() / 1000 };
  railwatchStore.setState({ rehearsal: { ...railwatchStore.getState().rehearsal, report: recent } });
  const command = vi.spyOn(railwatchApi, "command").mockResolvedValue({ cleared: 1 });
  render(<RehearsalPanel busy={null} runCommand={vi.fn()} />);
  await userEvent.click(screen.getByRole("button", { name: "清除记录" }));
  expect(command).toHaveBeenCalledWith("clearRehearsalHistory");
  await waitFor(() => expect(screen.queryByRole("button", { name: "查看结果" })).toBeNull());
  expect(railwatchStore.getState().rehearsal.report).toBeNull();
  expect(screen.getByText(/彩排冷却中/)).toBeTruthy();
  act(() => railwatchStore.getState().loadRehearsalHistory(recent));
  expect(railwatchStore.getState().rehearsal.report).toBeNull();
});

test("cancelled or failed clearing retains the report", async () => {
  railwatchStore.setState({ rehearsal: { ...railwatchStore.getState().rehearsal, report } });
  const command = vi.spyOn(railwatchApi, "command").mockResolvedValueOnce({ cancelled: true }).mockRejectedValueOnce(new Error("failed"));
  render(<RehearsalPanel busy={null} runCommand={vi.fn()} />);
  await userEvent.click(screen.getByRole("button", { name: "清除记录" }));
  expect(railwatchStore.getState().rehearsal.report).toEqual(report);
  // jsdom keeps the leaving spinner mounted after loading has finished.
  await userEvent.click(screen.getByRole("button", { name: /清除记录/ }));
  expect(await screen.findByRole("alert")).toHaveProperty("textContent", "清除失败，彩排记录已保留，请稍后重试。");
  expect(command).toHaveBeenCalledTimes(2);
  expect(railwatchStore.getState().rehearsal.report).toEqual(report);
});
