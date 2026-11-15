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
const downloadChromeDriver = vi.fn<() => Promise<{ chromedriver_path: string; chrome_version: string }>>();
const getRuntimeInfo = vi.fn<() => Promise<typeof defaultRuntimeInfo>>();
const loadTripState = vi.fn();
let emitBridgeEvent: ((event: BridgeEvent) => void) | null = null;
const command = vi.fn(async (name: string, _payload: Record<string, unknown> = {}) => {
  if (name === "checkEnvironment") return checkEnvironment();
  if (name === "downloadChromeDriver") return downloadChromeDriver();
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
  downloadChromeDriver.mockReset().mockResolvedValue({ chromedriver_path: "driver", chrome_version: "Chrome 158" });
  getRuntimeInfo.mockReset().mockResolvedValue(defaultRuntimeInfo);
  loadTripState.mockReset().mockResolvedValue({
    saved_config: defaultConfig, saved_at: null,
    draft: { status: "missing", draft: null, warning: null },
  });
  const initial = createRailWatchStore().getState();
  railwatchStore.setState({
    config: initial.config, status: initial.status, runtime: initial.runtime,
    environmentProgress: null, environmentProgressVisible: false,
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

  expect(screen.getAllByText("环境检查失败，请重试。").length).toBeGreaterThan(0);
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

test("environment download progress can be minimized and reopened after changing pages", async () => {
  let finish!: (status: RailWatchStatus) => void;
  checkEnvironment.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  await openApp();
  act(() => railwatchStore.getState().setActivePage("系统设置"));
  fireEvent.click(screen.getByRole("button", { name: "检查环境" }));
  expect(screen.getByRole("dialog", { name: "环境检查" })).toBeTruthy();
  expect(railwatchStore.getState().environmentProgress?.status).toBe("running");

  const started_at = Date.now() / 1000;
  act(() => emitBridgeEvent?.({ event: "environmentProgress", payload: {
    operation: "checkEnvironment", status: "running", stage: "downloading", started_at, updated_at: started_at,
    message: "正在下载 ChromeDriver", source: "npmmirror 镜像", downloaded_bytes: 5242880,
    total_bytes: 10485760, bytes_per_second: 1048576, eta_seconds: 5,
  } }));
  expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBe("50");
  fireEvent.click(screen.getByRole("button", { name: "收起" }));
  await advance(500);
  expect(railwatchStore.getState().environmentProgressVisible).toBe(false);
  expect(railwatchStore.getState().environmentProgress?.status).toBe("running");
  act(() => railwatchStore.getState().setActivePage("仪表盘"));
  await advance(2000);
  act(() => railwatchStore.getState().setActivePage("系统设置"));
  fireEvent.click(screen.getByRole("button", { name: "查看进度" }));
  expect(screen.getByRole("dialog", { name: "环境检查" })).toBeTruthy();
  expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBe("50");
  expect(checkEnvironment).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("button", { name: "下载 ChromeDriver" }).hasAttribute("disabled")).toBe(true);
  await act(async () => { finish({ ...defaultStatus, environment_ready: true }); });
  expect(railwatchStore.getState().environmentProgress?.status).toBe("success");
  expect(screen.getByRole("dialog", { name: "环境检查" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "关闭" })).toBeTruthy();
});

test("manual driver download owns the same progress dialog and cannot overlap a check", async () => {
  let finish!: (result: { chromedriver_path: string; chrome_version: string }) => void;
  downloadChromeDriver.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  await openApp();
  act(() => railwatchStore.getState().setActivePage("系统设置"));
  fireEvent.click(screen.getByRole("button", { name: "下载 ChromeDriver" }));
  expect(screen.getByRole("dialog", { name: "下载 ChromeDriver" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "检查环境" }).hasAttribute("disabled")).toBe(true);
  act(() => emitBridgeEvent?.({ event: "environmentProgress", payload: {
    operation: "downloadChromeDriver", status: "error", stage: "error",
    started_at: Date.now() / 1000, updated_at: Date.now() / 1000, message: "请先安装 Chrome 浏览器。",
  } }));
  await act(async () => { finish({ chromedriver_path: "", chrome_version: "" }); });
  expect(railwatchStore.getState().environmentProgress?.status).toBe("error");
  expect(railwatchStore.getState().environmentProgress?.message).toBe("请先安装 Chrome 浏览器。");
  expect(checkEnvironment).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "检查环境" }).hasAttribute("disabled")).toBe(false);
});

test("retry clears the previous failure and runtime interruption ends the progress display", async () => {
  checkEnvironment.mockRejectedValueOnce(new Error("下载失败"));
  await openApp();
  act(() => railwatchStore.getState().setActivePage("系统设置"));
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "检查环境" })));
  expect(railwatchStore.getState().environmentProgress?.status).toBe("error");
  checkEnvironment.mockImplementation(() => new Promise(() => undefined));
  fireEvent.click(screen.getByRole("button", { name: "检查环境" }));
  expect(railwatchStore.getState().environmentProgress?.status).toBe("running");
  expect(railwatchStore.getState().environmentProgress?.message).not.toBe("下载失败");
  act(() => emitBridgeEvent?.({ event: "runtimeExit", payload: { message: "连接中断" } }));
  expect(railwatchStore.getState().environmentProgress?.status).toBe("error");
  expect(railwatchStore.getState().environmentProgress?.message).toContain("运行时中断");
});

test("a minimized driver download reports completion without reopening the dialog", async () => {
  let finish!: (result: { chromedriver_path: string; chrome_version: string }) => void;
  downloadChromeDriver.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  await openApp();
  act(() => railwatchStore.getState().setActivePage("系统设置"));
  fireEvent.click(screen.getByRole("button", { name: "下载 ChromeDriver" }));
  fireEvent.click(screen.getByRole("button", { name: "收起" }));
  act(() => railwatchStore.getState().setActivePage("仪表盘"));
  await act(async () => { finish({ chromedriver_path: "driver", chrome_version: "Chrome 158" }); });
  expect(railwatchStore.getState().environmentProgressVisible).toBe(false);
  expect(railwatchStore.getState().environmentProgress?.status).toBe("success");
  expect(screen.getByText("ChromeDriver 已安装，可以检查运行环境。").closest(".ant-message-notice")).toBeTruthy();
  checkEnvironment.mockImplementation(() => new Promise(() => undefined));
  act(() => railwatchStore.getState().setActivePage("系统设置"));
  fireEvent.click(screen.getByRole("button", { name: "检查环境" }));
  await advance(1600);
  // JSDOM does not dispatch the CSS animation end; destruction starts its exit now.
  expect(screen.getByText("ChromeDriver 已安装，可以检查运行环境。").closest('[class*="-leave"]')).toBeTruthy();
});

test("starting another environment operation clears the previous success notice immediately", async () => {
  await openApp();
  act(() => railwatchStore.getState().setActivePage("系统设置"));
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "检查环境" })));
  expect(screen.getByText("环境检查完成，运行环境已就绪。")).toBeTruthy();
  checkEnvironment.mockImplementation(() => new Promise(() => undefined));
  fireEvent.click(screen.getByRole("button", { name: "检查环境" }));
  await advance(1600);
  expect(railwatchStore.getState().environmentProgress?.status).toBe("running");
  expect(screen.getByText("环境检查完成，运行环境已就绪。").closest('[class*="-leave"]')).toBeTruthy();
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

test("startup probes concurrently without blocking, applies labels updates, and pauses polling while hidden", async () => {
  let resolveRuntime!: () => void;
  getRuntimeInfo.mockImplementation(
    () => new Promise(resolve => {
      resolveRuntime = () => resolve({
        ...defaultRuntimeInfo,
        network_ok: false,
        network_label: "检测中",
        railway_ok: false,
        railway_label: "检测中",
        connectivity_pending: true,
      });
    }),
  );
  await openApp();

  expect(command).toHaveBeenCalledWith("getRuntimeInfo", { probe: false });
  expect(loadTripState).toHaveBeenCalled();

  await act(async () => { resolveRuntime(); });
  expect(railwatchStore.getState().runtime.network_label).toBe("检测中");

  act(() => {
    emitBridgeEvent?.({
      event: "labels",
      payload: { network_ok: true, network_label: "正常", railway_ok: true, railway_label: "正常", connectivity_pending: false },
    });
  });
  expect(railwatchStore.getState().runtime.network_ok).toBe(true);
  expect(railwatchStore.getState().runtime.network_label).toBe("正常");
  expect(railwatchStore.getState().runtime.railway_label).toBe("正常");

  const callsBeforeHidden = command.mock.calls.filter(([name]) => name === "getRuntimeInfo").length;
  Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
  try {
    await advance(180000);
    expect(command.mock.calls.filter(([name]) => name === "getRuntimeInfo")).toHaveLength(callsBeforeHidden);

    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(command.mock.calls.filter(([name]) => name === "getRuntimeInfo").length).toBeGreaterThan(callsBeforeHidden);
  } finally {
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
  }
});

test("startup applies runtimeInfo before loadTrip finishes and does not overwrite earlier labels events", async () => {
  let resolveRuntime!: () => void;
  let resolveTrip!: () => void;
  getRuntimeInfo.mockImplementation(
    () => new Promise(resolve => {
      resolveRuntime = () => resolve({
        ...defaultRuntimeInfo,
        chrome_version: "Chrome 142",
        network_ok: false,
        network_label: "检测中",
        railway_ok: false,
        railway_label: "检测中",
        connectivity_pending: true,
      });
    }),
  );
  loadTripState.mockImplementation(
    () => new Promise(resolve => {
      resolveTrip = () => resolve({
        saved_config: defaultConfig,
        saved_at: null,
        draft: { status: "missing", draft: null, warning: null },
      });
    }),
  );

  await openApp();

  // Labels arrive before getRuntimeInfo returns and while loadTripState is still pending.
  act(() => {
    emitBridgeEvent?.({
      event: "labels",
      payload: { network_ok: true, network_label: "正常", railway_ok: true, railway_label: "正常", connectivity_pending: false },
    });
  });
  expect(railwatchStore.getState().runtime.network_label).toBe("正常");

  // Even while loadTripState is still pending, getRuntimeInfo applies immediately without clobbering resolved labels.
  await act(async () => { resolveRuntime(); });
  expect(railwatchStore.getState().runtime.chrome_version).toBe("Chrome 142");
  expect(railwatchStore.getState().runtime.network_label).toBe("正常");
  expect(railwatchStore.getState().runtime.railway_label).toBe("正常");

  await act(async () => { resolveTrip(); });
  expect(railwatchStore.getState().runtime.network_label).toBe("正常");
  expect(railwatchStore.getState().tripInitialized).toBe(true);
});
