// @vitest-environment jsdom
import { StrictMode, type ReactNode } from "react";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { RailWatchApp } from "./App";
import {
  createRailWatchStore,
  defaultConfig,
  defaultRuntimeInfo,
  defaultStatus,
  railwatchStore,
} from "./store/railwatchStore";
import type { BridgeEvent, RailWatchStatus } from "./types";

vi.mock("./components/Shell", () => ({
  ShellLayout: ({ children }: { children: ReactNode }) => children,
}));

const checkEnvironment = vi.fn<() => Promise<RailWatchStatus>>();
const getRuntimeInfo = vi.fn<() => Promise<typeof defaultRuntimeInfo>>();
const loadTripState = vi.fn();
let emitBridgeEvent: ((event: BridgeEvent) => void) | null = null;
const command = vi.fn(async (name: string, _payload: Record<string, unknown> = {}) => {
  if (name === "checkEnvironment") return checkEnvironment();
  if (name === "getRuntimeInfo") return getRuntimeInfo();
  if (name === "loadTripState") return loadTripState();
  if (name === "loadPreferences") return {
    theme: "light", close_to_tray: false, auto_rehearsal: false, notification_settings: {},
  };
  if (name === "rehearsalHistory") return { items: [] };
  return {};
});

beforeEach(() => {
  vi.useFakeTimers();
  vi.clearAllMocks();
  emitBridgeEvent = null;
  checkEnvironment.mockReset().mockResolvedValue({ ...defaultStatus, environment_ready: true });
  getRuntimeInfo.mockReset().mockResolvedValue(defaultRuntimeInfo);
  loadTripState.mockReset().mockResolvedValue({
    saved_config: defaultConfig, saved_at: null,
    draft: { status: "missing", draft: null, warning: null },
  });
  const initial = createRailWatchStore().getState();
  railwatchStore.setState({
    config: initial.config, status: initial.status, runtime: initial.runtime,
    rehearsal: initial.rehearsal, rehearsalEnabled: false,
    activePage: "仪表盘", pageSection: null, eventPanelVisible: false,
    lastHumanAction: null, hits: [], logs: [],
    tripInitialized: false, editRevision: 0, draftRevision: 0,
    draftSaveState: "idle", savedConfig: null,
  });
  window.railwatch = {
    command, stageDraft: vi.fn(),
    onEvent: (callback: (event: BridgeEvent) => void) => {
      emitBridgeEvent = callback;
      return () => { emitBridgeEvent = null; };
    }, onConfirmRequest: () => () => {},
    onUpdateState: () => () => {}, stopUrgentAlert: vi.fn(),
  } as unknown as NonNullable<typeof window.railwatch>;
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  delete window.railwatch;
});

async function openApp() {
  await act(async () => { render(<StrictMode><RailWatchApp /></StrictMode>); });
}

async function advance(milliseconds: number) {
  await act(async () => { await vi.advanceTimersByTimeAsync(milliseconds); });
}

test("dashboard navigates first, prepares for 1.5 seconds, then checks once and applies the result", async () => {
  let finish!: (status: RailWatchStatus) => void;
  checkEnvironment.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  await openApp();

  fireEvent.click(screen.getByRole("button", { name: "检查环境" }));
  expect(railwatchStore.getState().activePage).toBe("系统设置");
  expect(railwatchStore.getState().pageSection).toBe("settings-environment");
  expect(screen.queryByRole("heading", { name: "环境与登录" })).toBeNull();
  expect(screen.queryByRole("navigation", { name: "设置分组" })).toBeNull();
  expect(screen.queryByRole("button", { name: /检查环境/ })).toBeNull();
  expect(screen.getByRole("status", { name: "环境检查进度" }).textContent).toContain("检查程序启动中");
  await advance(1499);
  expect(checkEnvironment).not.toHaveBeenCalled();

  await advance(1);
  expect(checkEnvironment).toHaveBeenCalledTimes(1);
  expect(command).toHaveBeenCalledWith("checkEnvironment", {});
  expect(screen.queryByRole("status", { name: "环境检查进度" })).toBeNull();
  expect(screen.getByRole("heading", { name: "环境与登录" })).toBeTruthy();
  const button = screen.getByRole("button", { name: /检查环境/ });
  expect(button.hasAttribute("disabled")).toBe(true);
  expect(button.classList.contains("ant-btn-loading")).toBe(true);
  expect(screen.getByRole("button", { name: /打开登录/ }).hasAttribute("disabled")).toBe(true);
  expect(screen.getByRole("button", { name: "检查登录" }).hasAttribute("disabled")).toBe(true);
  expect(screen.queryByText("环境检查完成，运行环境已就绪。")).toBeNull();
  fireEvent.click(button);
  await advance(1500);
  expect(checkEnvironment).toHaveBeenCalledTimes(1);

  await act(async () => { finish({ ...defaultStatus, environment_ready: true }); });
  expect(railwatchStore.getState().status.environment_ready).toBe(true);
  expect(screen.getByRole("button", { name: /打开登录/ }).hasAttribute("disabled")).toBe(false);
  expect(screen.getByRole("button", { name: "检查登录" }).hasAttribute("disabled")).toBe(false);
  expect(screen.queryByRole("status", { name: "环境检查进度" })).toBeNull();
  expect(button.hasAttribute("disabled")).toBe(false);
  expect(screen.getByText("环境检查完成，运行环境已就绪。").closest(".ant-message-notice")?.classList
    .contains("railwatch-environment-success")).toBe(true);
});

test("leaving during preparation cancels it, and reopening settings keeps the manual check immediate", async () => {
  await openApp();
  fireEvent.click(screen.getByRole("button", { name: "检查环境" }));
  await advance(700);
  act(() => railwatchStore.getState().setActivePage("仪表盘"));
  await advance(1500);
  expect(checkEnvironment).not.toHaveBeenCalled();

  act(() => railwatchStore.getState().setActivePage("系统设置"));
  expect(screen.queryByRole("status", { name: "环境检查进度" })).toBeNull();
  await advance(1500);
  expect(checkEnvironment).not.toHaveBeenCalled();
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "检查环境" })); });
  expect(checkEnvironment).toHaveBeenCalledTimes(1);
  expect(command).toHaveBeenCalledWith("checkEnvironment", {});
  expect(railwatchStore.getState().status.environment_ready).toBe(true);
  expect(screen.getAllByText("环境检查完成，运行环境已就绪。")).toHaveLength(1);
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "检查环境" })); });
  expect(checkEnvironment).toHaveBeenCalledTimes(2);
  expect(screen.getAllByText("环境检查完成，运行环境已就绪。")).toHaveLength(1);
});

test.each(["getRuntimeInfo", "loadTripState"])("finishing startup %s keeps a slow environment check loading", async (startupCommand) => {
  let finishStartup!: () => void;
  const startup = new Promise<void>(resolve => { finishStartup = resolve; });
  if (startupCommand === "getRuntimeInfo") {
    getRuntimeInfo.mockImplementation(async () => { await startup; return defaultRuntimeInfo; });
  } else {
    loadTripState.mockImplementation(async () => {
      await startup;
      return { saved_config: defaultConfig, saved_at: null, draft: { status: "missing", draft: null, warning: null } };
    });
  }
  let finishCheck!: (status: RailWatchStatus) => void;
  checkEnvironment.mockImplementation(() => new Promise(resolve => { finishCheck = resolve; }));
  await openApp();
  fireEvent.click(screen.getByRole("button", { name: "检查环境" }));
  await advance(1500);
  expect(checkEnvironment).toHaveBeenCalledTimes(1);

  await act(async () => { finishStartup(); });
  await advance(60000);
  const button = screen.getByRole("button", { name: /检查环境/ });
  expect(button.hasAttribute("disabled")).toBe(true);
  expect(button.classList.contains("ant-btn-loading")).toBe(true);
  expect(screen.queryByText("环境检查完成，运行环境已就绪。")).toBeNull();
  expect(screen.getByRole("button", { name: /打开登录/ }).hasAttribute("disabled")).toBe(true);
  fireEvent.click(button);
  expect(checkEnvironment).toHaveBeenCalledTimes(1);

  await act(async () => { finishCheck({ ...defaultStatus, environment_ready: true }); });
  expect(button.hasAttribute("disabled")).toBe(false);
  expect(button.classList.contains("ant-btn-loading")).toBe(false);
  expect(screen.getByText("环境检查完成，运行环境已就绪。")).toBeTruthy();
});

test("returning through the dashboard does not start another environment check while the first is pending", async () => {
  let finishCheck!: (status: RailWatchStatus) => void;
  checkEnvironment.mockImplementation(() => new Promise(resolve => { finishCheck = resolve; }));
  await openApp();
  fireEvent.click(screen.getByRole("button", { name: "检查环境" }));
  await advance(1500);

  act(() => railwatchStore.getState().setActivePage("仪表盘"));
  fireEvent.click(screen.getByRole("button", { name: "检查环境" }));
  await advance(1500);
  expect(checkEnvironment).toHaveBeenCalledTimes(1);
  const button = screen.getByRole("button", { name: /检查环境/ });
  expect(button.hasAttribute("disabled")).toBe(true);
  expect(button.classList.contains("ant-btn-loading")).toBe(true);

  await act(async () => { finishCheck({ ...defaultStatus, environment_ready: true }); });
  expect(button.hasAttribute("disabled")).toBe(false);
  expect(button.classList.contains("ant-btn-loading")).toBe(false);
});

test("a fresh dashboard click gets a full delay after an earlier preparation was cancelled", async () => {
  await openApp();
  fireEvent.click(screen.getByRole("button", { name: "检查环境" }));
  await advance(1000);
  act(() => railwatchStore.getState().setActivePage("仪表盘"));
  fireEvent.click(screen.getByRole("button", { name: "检查环境" }));

  await advance(1499);
  expect(checkEnvironment).not.toHaveBeenCalled();
  await advance(1);
  expect(checkEnvironment).toHaveBeenCalledTimes(1);
});

test("automatic check errors use the existing error message and allow a manual retry", async () => {
  checkEnvironment.mockRejectedValueOnce(new Error("环境检查失败，请重试。"));
  await openApp();
  fireEvent.click(screen.getByRole("button", { name: "检查环境" }));
  await advance(1500);

  expect(screen.getByText("环境检查失败，请重试。")).toBeTruthy();
  expect(screen.queryByText("环境检查完成，运行环境已就绪。")).toBeNull();
  expect(screen.getByRole("button", { name: /打开登录/ }).hasAttribute("disabled")).toBe(true);
  expect(screen.queryByRole("status", { name: "环境检查进度" })).toBeNull();
  expect(screen.getByRole("button", { name: "检查环境" }).hasAttribute("disabled")).toBe(false);
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "检查环境" })); });
  expect(checkEnvironment).toHaveBeenCalledTimes(2);
  expect(railwatchStore.getState().status.environment_ready).toBe(true);
  expect(screen.getByText("环境检查完成，运行环境已就绪。")).toBeTruthy();
  await advance(1500);
  expect(checkEnvironment).toHaveBeenCalledTimes(2);
});

test.each([false, true])("a failed environment result never shows success even with previous readiness %s", async (environment_ready) => {
  checkEnvironment.mockResolvedValue({
    ...defaultStatus, environment_ready, phase: "error", risk_level: "critical",
    error_message: "Chrome 驱动不可用", status_message: "Chrome 驱动不可用",
  });
  await openApp();
  act(() => railwatchStore.getState().setActivePage("系统设置"));
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "检查环境" })); });
  expect(checkEnvironment).toHaveBeenCalledTimes(1);
  expect(railwatchStore.getState().status.error_message).toBe("Chrome 驱动不可用");
  expect(screen.queryByText("环境检查完成，运行环境已就绪。")).toBeNull();
});

test("a runtime exit after a login setup warning still offers runtime recovery", async () => {
  await openApp();
  act(() => emitBridgeEvent?.({ event: "state", payload: {
    ...defaultStatus,
    phase: "error",
    risk_level: "warning",
    status_message: "请先打开登录页。",
    error_message: "请先打开登录页。",
  } }));
  expect(screen.getByRole("button", { name: "检查环境" })).toBeTruthy();

  act(() => emitBridgeEvent?.({ event: "runtimeExit", payload: { message: "Python 运行时异常退出" } }));
  expect(screen.getByRole("heading", { name: "需要关注运行状态" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "查看运行详情" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: "检查环境" })).toBeNull();
});
