// @vitest-environment jsdom
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { railwatchApi } from "../lib/railwatchApi";
import {
  defaultRuntimeInfo,
  defaultStatus,
  railwatchStore,
} from "../store/railwatchStore";
import { SettingsPage } from "./SettingsPage";
import type { CommandRunner } from "./componentTypes";
import type { RailWatchStatus } from "../types";

function resetStore() {
  railwatchStore.setState({
    environmentProgress: null, environmentProgressVisible: false,
    rehearsalEnabled: false,
    runtime: {
      ...defaultRuntimeInfo,
      data_dir: "C:/RailWatch/data",
      chromedriver_path: "D:/RailWatch/chromedriver.exe",
      chrome_version: "Chrome 148",
      state: { ...defaultStatus },
    },
    status: { ...defaultStatus },
  });
}

describe("SettingsPage", () => {
  beforeEach(() => {
    resetStore();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    cleanup();
  });

  test.each(["checkEnvironment", "downloadChromeDriver"] as const)("keeps progress accessible while %s runs and removes the summary on success", async operation => {
    railwatchStore.getState().beginEnvironmentOperation(operation);
    railwatchStore.getState().setEnvironmentProgressVisible(false);
    const runCommand = vi.fn(async () => undefined) as CommandRunner;
    const { container } = render(<SettingsPage busy={null} runCommand={runCommand} />);

    expect(container.querySelector(".environment-progress-summary")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "查看进度" }));
    expect(railwatchStore.getState().environmentProgressVisible).toBe(true);

    act(() => railwatchStore.getState().finishEnvironmentOperation(operation));
    expect(container.querySelector(".environment-progress-summary")).toBeNull();
    expect(screen.queryByRole("button", { name: "查看结果" })).toBeNull();
    expect(screen.queryByRole("button", { name: "查看进度" })).toBeNull();
    expect(screen.getByRole("button", { name: "检查环境" }).hasAttribute("disabled")).toBe(false);
  });

  test("keeps failed environment preparation visible and lets the user reopen its result", async () => {
    railwatchStore.getState().beginEnvironmentOperation("checkEnvironment");
    railwatchStore.getState().finishEnvironmentOperation("checkEnvironment", "驱动下载失败，请检查网络。");
    railwatchStore.getState().setEnvironmentProgressVisible(false);
    const runCommand = vi.fn(async () => undefined) as CommandRunner;
    render(<SettingsPage busy={null} runCommand={runCommand} />);

    expect(screen.getByText("驱动下载失败，请检查网络。")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "查看结果" }));
    expect(railwatchStore.getState().environmentProgressVisible).toBe(true);
    expect(screen.getByRole("button", { name: "检查环境" }).hasAttribute("disabled")).toBe(false);
  });

  test("login stays disabled until the environment is ready and locks again if readiness is lost", async () => {
    railwatchStore.setState({ runtime: {
      ...railwatchStore.getState().runtime,
      core_available: true, selenium_available: true, chromedriver_manager_available: true,
      network_ok: true, railway_ok: true,
    } });
    const runCommand = vi.fn(async () => undefined) as CommandRunner;
    render(<SettingsPage busy={null} runCommand={runCommand} />);
    const login = screen.getByRole("button", { name: /打开登录/ });
    const checkLogin = screen.getByRole("button", { name: /检查登录/ });
    expect(login.hasAttribute("disabled")).toBe(true);
    expect(checkLogin.hasAttribute("disabled")).toBe(true);
    expect(screen.getByRole("status").textContent).toBe("请先检查运行环境，再打开登录。");
    await userEvent.click(login);
    await userEvent.click(checkLogin);
    expect(runCommand).not.toHaveBeenCalled();

    act(() => railwatchStore.setState({ status: { ...defaultStatus, environment_ready: true } }));
    expect(login.hasAttribute("disabled")).toBe(false);
    expect(checkLogin.hasAttribute("disabled")).toBe(false);
    await userEvent.click(login);
    expect(runCommand).toHaveBeenCalledWith("openLogin");

    act(() => railwatchStore.setState({ status: { ...defaultStatus } }));
    expect(login.hasAttribute("disabled")).toBe(true);
    expect(checkLogin.hasAttribute("disabled")).toBe(true);
    await userEvent.click(login);
    await userEvent.click(checkLogin);
    expect(runCommand).toHaveBeenCalledTimes(1);
  });

  test("login is disabled during an environment recheck even when the previous check passed", async () => {
    railwatchStore.setState({ status: { ...defaultStatus, environment_ready: true } });
    const runCommand = vi.fn(async () => undefined) as CommandRunner;
    const page = render(<SettingsPage busy="checkEnvironment" runCommand={runCommand} />);
    const login = screen.getByRole("button", { name: /打开登录/ });
    const checkLogin = screen.getByRole("button", { name: /检查登录/ });
    expect(login.hasAttribute("disabled")).toBe(true);
    expect(checkLogin.hasAttribute("disabled")).toBe(true);
    expect(screen.getByRole("status").textContent).toContain("首次使用可能需要下载 Chrome 或驱动");
    expect(screen.getByRole("button", { name: "下载 ChromeDriver" }).hasAttribute("disabled")).toBe(true);
    await userEvent.click(login);
    await userEvent.click(checkLogin);
    expect(runCommand).not.toHaveBeenCalled();

    page.rerender(<SettingsPage busy={null} runCommand={runCommand} />);
    expect(login.hasAttribute("disabled")).toBe(false);
    expect(checkLogin.hasAttribute("disabled")).toBe(false);
    expect(screen.getByRole("button", { name: "下载 ChromeDriver" }).hasAttribute("disabled")).toBe(false);
    await userEvent.click(login);
    expect(runCommand).toHaveBeenCalledWith("openLogin");
  });

  test("login check shows progress and its returned result", async () => {
    railwatchStore.setState({ status: { ...defaultStatus, environment_ready: true } });
    let finish!: (value: RailWatchStatus) => void;
    const runCommand = vi.fn(() => new Promise<RailWatchStatus>((resolve) => { finish = resolve; }));
    render(<SettingsPage busy={null} runCommand={runCommand as CommandRunner} />);
    await userEvent.click(screen.getByRole("button", { name: /检查登录/ }));
    expect(runCommand).toHaveBeenCalledWith("checkLogin");
    expect(screen.getByRole("status").textContent).toContain("正在检查");
    await act(async () => finish({ ...defaultStatus, environment_ready: true, login_ready: true, status_message: "登录已验证" }));
    expect(screen.getByRole("status").textContent).toBe("登录已验证");
  });

  test.each(["请先打开登录页。", "暂时无法确认登录状态，请检查网络后重试。"])("shows unsuccessful login result: %s", async (text) => {
    railwatchStore.setState({ status: { ...defaultStatus, environment_ready: true } });
    const runCommand = vi.fn(async () => ({ ...defaultStatus, environment_ready: true, login_ready: false, status_message: text }));
    render(<SettingsPage busy={null} runCommand={runCommand as CommandRunner} />);
    await userEvent.click(screen.getByRole("button", { name: /检查登录/ }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe(text));
  });

  test("a failed command does not leave login checking indefinitely", async () => {
    railwatchStore.setState({ status: { ...defaultStatus, environment_ready: true } });
    const runCommand = vi.fn(async () => undefined) as CommandRunner;
    render(<SettingsPage busy={null} runCommand={runCommand} />);
    await userEvent.click(screen.getByRole("button", { name: /检查登录/ }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("检查未完成"));
  });

  test("shows local runtime data and separated maintenance actions", () => {
    const runCommand = vi.fn(async () => undefined) as CommandRunner;

    render(<SettingsPage busy={null} runCommand={runCommand} />);

    expect(screen.getByRole("heading", { name: "外观" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "环境与登录" })).toBeTruthy();
    expect(screen.getByText("C:/RailWatch/data")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "本地数据" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "维护操作" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "应用更新" })).toBeNull();
    expect(screen.queryByRole("button", { name: /检查更新/ })).toBeNull();
    expect(screen.getByRole("button", { name: /清除数据/ })).toBeTruthy();

    const checkEnvironment = screen.getByRole("button", { name: /检查环境/ });
    expect(checkEnvironment).toBeTruthy();
    expect(
      screen.getByRole("button", { name: /下载 ChromeDriver/ }),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: /打开登录/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /检查登录/ })).toBeTruthy();
    expect(checkEnvironment.closest(".maintenance")).toBeNull();

    expect(screen.getByRole("button", { name: /关闭浏览器/ })).toBeTruthy();
    const clearLocalData = screen.getByRole("button", { name: /清除数据/ });
    expect(clearLocalData).toBeTruthy();
    expect(clearLocalData.closest(".maintenance")).toBeTruthy();
  });

  test("opens the trusted data directory without sending the displayed path", async () => {
    const open = vi.spyOn(railwatchApi, "openDataDir").mockResolvedValue({ ok: true });
    render(<SettingsPage busy={null} runCommand={vi.fn(async () => undefined) as CommandRunner} />);

    await userEvent.click(screen.getByRole("button", { name: "打开目录" }));

    expect(open).toHaveBeenCalledExactlyOnceWith();
    expect((await screen.findByText("已打开数据目录。")).getAttribute("role")).toBe("status");
  });

  test("shows a reported directory open failure", async () => {
    vi.spyOn(railwatchApi, "openDataDir").mockResolvedValue({ ok: false, error: "本地数据目录暂不可用。" });
    render(<SettingsPage busy={null} runCommand={vi.fn(async () => undefined) as CommandRunner} />);

    await userEvent.click(screen.getByRole("button", { name: "打开目录" }));

    expect((await screen.findByText("本地数据目录暂不可用。")).getAttribute("role")).toBe("alert");
  });

  test.each([
    ["exportTripBundle", "导出脱敏备份", "备份导出成功。", "已取消导出备份。"],
    ["importTripBundle", "导入备份", "备份导入成功。", "已取消导入备份。"],
  ] as const)("reports success and cancellation from %s", async (method, buttonName, success, cancelled) => {
    const transfer = vi.spyOn(railwatchApi, method).mockResolvedValueOnce({ ok: true }).mockResolvedValueOnce({ cancelled: true });
    const runCommand = vi.fn(async () => undefined) as CommandRunner;
    render(<SettingsPage busy={null} runCommand={runCommand} />);
    const button = screen.getByRole("button", { name: buttonName });

    await userEvent.click(button);
    expect(transfer).toHaveBeenCalledExactlyOnceWith();
    expect((await screen.findByText(success)).getAttribute("role")).toBe("status");

    await userEvent.click(button);
    expect((await screen.findByText(cancelled)).getAttribute("role")).toBe("status");
    expect(screen.queryByText(success)).toBeNull();
    expect(runCommand).not.toHaveBeenCalled();
  });

  test("shows a rejected backup and keeps another file picker from opening before it finishes", async () => {
    let rejectImport!: (error: Error) => void;
    vi.spyOn(railwatchApi, "importTripBundle").mockReturnValue(new Promise((_, reject) => { rejectImport = reject; }));
    const exportBackup = vi.spyOn(railwatchApi, "exportTripBundle");
    render(<SettingsPage busy={null} runCommand={vi.fn(async () => undefined) as CommandRunner} />);

    await userEvent.click(screen.getByRole("button", { name: "导入备份" }));
    const exportButton = screen.getByRole<HTMLButtonElement>("button", { name: "导出脱敏备份" });
    expect(exportButton.disabled).toBe(true);
    await userEvent.click(exportButton);
    expect(exportBackup).not.toHaveBeenCalled();

    act(() => rejectImport(new Error("Error invoking remote method 'railwatch:import-trip-bundle': Error: 备份文件须包含一个 JSON 对象。")));
    expect((await screen.findByText("备份文件须包含一个 JSON 对象。")).getAttribute("role")).toBe("alert");
    expect(exportButton.disabled).toBe(false);
  });

  test("saves the tray preference as a patch", async () => {
    const command = vi.spyOn(railwatchApi, "command").mockImplementation(async (_name, payload = {}) => ({
      theme: "dark", close_to_tray: payload.close_to_tray === true,
      notification_settings: {},
    }) as never);
    render(<SettingsPage busy={null} runCommand={vi.fn(async () => undefined) as CommandRunner} />);
    const toggle = await screen.findByRole("switch", { name: "关闭到托盘" });
    await waitFor(() => expect(toggle.hasAttribute("disabled")).toBe(false));
    await userEvent.click(toggle);
    await waitFor(() => expect(command).toHaveBeenCalledWith("savePreferences", { close_to_tray: true }));
    expect(toggle.getAttribute("aria-checked")).toBe("true");
  });

  test("defaults to 30 minutes and saves only the selected sale reminder lead time", async () => {
    const command = vi.spyOn(railwatchApi, "command").mockImplementation(async (_name, payload = {}) => ({
      theme: "light", close_to_tray: false, notification_settings: {},
      sale_reminder_lead_minutes: payload.sale_reminder_lead_minutes,
    }) as never);
    render(<SettingsPage busy={null} runCommand={vi.fn(async () => undefined) as CommandRunner} />);
    const select = screen.getByRole<HTMLSelectElement>("combobox", { name: "起售提醒提前时间" });
    await waitFor(() => expect(select.disabled).toBe(false));
    expect(select.value).toBe("30");
    expect(within(select).getAllByRole("option").map(option => option.textContent)).toEqual([
      "10 分钟", "15 分钟", "30 分钟", "60 分钟",
    ]);
    await userEvent.selectOptions(select, "60");
    expect(command).toHaveBeenCalledWith("savePreferences", { sale_reminder_lead_minutes: 60 });
    await waitFor(() => expect(select.value).toBe("60"));
  });

  test("shows the saved sale reminder lead time and preserves it after a failed save", async () => {
    vi.spyOn(railwatchApi, "command").mockImplementation(async name => {
      if (name === "savePreferences") throw new Error("save failed");
      return { theme: "light", close_to_tray: false, notification_settings: {}, sale_reminder_lead_minutes: 75 } as never;
    });
    render(<SettingsPage busy={null} runCommand={vi.fn(async () => undefined) as CommandRunner} />);
    const select = screen.getByRole<HTMLSelectElement>("combobox", { name: "起售提醒提前时间" });
    await waitFor(() => expect(select.disabled).toBe(false));
    expect(select.value).toBe("75");
    await userEvent.selectOptions(select, "15");
    expect((await screen.findByText("起售提醒提前时间未保存，请重试。")).getAttribute("role")).toBe("alert");
    expect(select.value).toBe("75");
  });

  test("idle login keeping follows the saved preference and a save round-trips", async () => {
    let saved = false;
    const command = vi.spyOn(railwatchApi, "command").mockImplementation(async (name, payload = {}) => {
      if (name === "savePreferences" && "idle_keep_alive" in payload) saved = payload.idle_keep_alive as boolean;
      return { theme: "light", close_to_tray: false, idle_keep_alive: saved, notification_settings: {} } as never;
    });
    render(<SettingsPage busy={null} runCommand={vi.fn(async () => undefined) as CommandRunner} />);
    const toggle = screen.getByRole("switch", { name: "空闲时保持登录" });
    await waitFor(() => expect(toggle.hasAttribute("disabled")).toBe(false));
    expect(toggle.getAttribute("aria-checked")).toBe("false");
    expect(screen.getByText(/每 5 分钟检查一次登录状态，只检查登录、不查余票/)).toBeTruthy();
    await userEvent.click(toggle);
    expect(command).toHaveBeenCalledWith("savePreferences", { idle_keep_alive: true });
    await waitFor(() => expect(toggle.getAttribute("aria-checked")).toBe("true"));
  });

  test("idle login keeping is off when no preference was ever saved", async () => {
    vi.spyOn(railwatchApi, "command").mockImplementation(async () => (
      { theme: "light", close_to_tray: false, notification_settings: {} }) as never);
    render(<SettingsPage busy={null} runCommand={vi.fn(async () => undefined) as CommandRunner} />);
    const toggle = screen.getByRole("switch", { name: "空闲时保持登录" });
    await waitFor(() => expect(toggle.hasAttribute("disabled")).toBe(false));
    expect(toggle.getAttribute("aria-checked")).toBe("false");
  });

  test("loads the global maintenance preference and saves it between idle login and sale reminder settings", async () => {
    const command = vi.spyOn(railwatchApi, "command").mockImplementation(async (name, payload = {}) => ({
      theme: "light", close_to_tray: false, notification_settings: {},
      maintenance_sleep: name === "savePreferences" ? payload.maintenance_sleep : true,
    }) as never);
    render(<SettingsPage busy={null} runCommand={vi.fn(async () => undefined) as CommandRunner} />);
    const preferences = within(document.getElementById("settings-behavior")!);
    const idle = preferences.getByRole("switch", { name: "空闲时保持登录" });
    const toggle = preferences.getByRole("switch", { name: "夜间维护休眠" });
    const reminder = preferences.getByRole("combobox", { name: "起售提醒提前时间" });
    const row = toggle.closest(".setting-row");
    expect(row?.previousElementSibling).toBe(idle.closest(".setting-row"));
    expect(row?.nextElementSibling).toBe(reminder.closest(".setting-row"));
    const help = preferences.getByText("监控期间在 12306 夜间维护时段（常规 01:00–05:00，周二 23:30 起）自动暂停查询，05:00 恢复（北京时间）。");
    expect(toggle.getAttribute("aria-describedby")).toBe(help.id);
    await waitFor(() => expect(toggle.getAttribute("aria-checked")).toBe("true"));
    await userEvent.click(toggle);
    expect(command).toHaveBeenCalledWith("savePreferences", { maintenance_sleep: false });
    await waitFor(() => expect(toggle.getAttribute("aria-checked")).toBe("false"));
    await userEvent.click(toggle);
    expect(command).toHaveBeenCalledWith("savePreferences", { maintenance_sleep: true });
    await waitFor(() => expect(toggle.getAttribute("aria-checked")).toBe("true"));
  });

  test("defaults maintenance sleep off and keeps the previous choice when saving fails", async () => {
    vi.spyOn(railwatchApi, "command").mockImplementation(async name => {
      if (name === "savePreferences") throw new Error("save failed");
      return { theme: "light", close_to_tray: false, notification_settings: {} } as never;
    });
    render(<SettingsPage busy={null} runCommand={vi.fn(async () => undefined) as CommandRunner} />);
    const toggle = screen.getByRole("switch", { name: "夜间维护休眠" });
    await waitFor(() => expect(toggle.hasAttribute("disabled")).toBe(false));
    expect(toggle.getAttribute("aria-checked")).toBe("false");
    await userEvent.click(toggle);
    expect((await screen.findByText("夜间维护休眠偏好未保存，请重试。")).getAttribute("role")).toBe("alert");
    expect(toggle.getAttribute("aria-checked")).toBe("false");
  });

  test("rehearsal is opt-in and a failed save preserves the current visibility", async () => {
    const command = vi.spyOn(railwatchApi, "command").mockImplementation(async (_name, payload = {}) => ({
      theme: "light", close_to_tray: false, auto_rehearsal: payload.auto_rehearsal,
      notification_settings: {},
    }) as never);
    render(<SettingsPage busy={null} runCommand={vi.fn(async () => undefined) as CommandRunner} />);
    const toggle = screen.getByRole("switch", { name: "启用起售彩排" });
    await waitFor(() => expect(toggle.hasAttribute("disabled")).toBe(false));
    expect(toggle.getAttribute("aria-checked")).toBe("false");
    await userEvent.click(toggle);
    expect(command).toHaveBeenCalledWith("savePreferences", { auto_rehearsal: true });
    await waitFor(() => expect(railwatchStore.getState().rehearsalEnabled).toBe(true));
    command.mockRejectedValueOnce(new Error("save failed"));
    await userEvent.click(toggle);
    await screen.findByText("自动彩排偏好未保存，请重试。");
    expect(railwatchStore.getState().rehearsalEnabled).toBe(true);
    await userEvent.click(toggle);
    await waitFor(() => expect(railwatchStore.getState().rehearsalEnabled).toBe(false));
    expect(toggle.getAttribute("aria-checked")).toBe("false");
  });

  test("macOS displays menu bar wording instead of tray wording", async () => {
    const appInfoSpy = vi.spyOn(railwatchApi, "getAppInfo").mockResolvedValue({
      appVersion: "1.0.0",
      electronVersion: "35.0.0",
      chromeVersion: "134.0.0.0",
      nodeVersion: "22.0.0",
      platform: "darwin",
      arch: "arm64",
      runningUnderARM64Translation: false,
    });
    vi.spyOn(railwatchApi, "command").mockResolvedValue({ theme: "light", close_to_tray: false, notification_settings: {} } as never);
    try {
      render(<SettingsPage busy={null} runCommand={vi.fn(async () => undefined) as CommandRunner} />);
      expect(await screen.findByRole("switch", { name: "关闭到菜单栏" })).toBeTruthy();
      expect(screen.getByText(/从顶部菜单栏图标重新打开或退出/)).toBeTruthy();
    } finally {
      appInfoSpy.mockRestore();
    }
  });

  test("macOS notification settings explain how to keep urgent notifications on screen", async () => {
    const appInfoSpy = vi.spyOn(railwatchApi, "getAppInfo").mockResolvedValue({
      appVersion: "1.0.0",
      electronVersion: "39.0.0",
      chromeVersion: "142.0.0.0",
      nodeVersion: "22.0.0",
      platform: "darwin",
      arch: "arm64",
      runningUnderARM64Translation: false,
    });
    vi.spyOn(railwatchApi, "command").mockResolvedValue(
      { theme: "light", close_to_tray: false, notification_settings: { desktop_urgent: true } } as never);
    try {
      render(<SettingsPage busy={null} runCommand={vi.fn(async () => undefined) as CommandRunner} />);
      expect(await screen.findByText(/把通知样式改为「持续」/)).toBeTruthy();
    } finally {
      appInfoSpy.mockRestore();
    }
  });
});
