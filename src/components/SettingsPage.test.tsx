// @vitest-environment jsdom
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
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

  test("login check shows progress and its returned result", async () => {
    let finish!: (value: RailWatchStatus) => void;
    const runCommand = vi.fn(() => new Promise<RailWatchStatus>((resolve) => { finish = resolve; }));
    render(<SettingsPage busy={null} runCommand={runCommand as CommandRunner} />);
    await userEvent.click(screen.getByRole("button", { name: /检查登录/ }));
    expect(runCommand).toHaveBeenCalledWith("checkLogin");
    expect(screen.getByRole("status").textContent).toContain("正在检查");
    await act(async () => finish({ ...defaultStatus, login_ready: true, status_message: "登录已验证" }));
    expect(screen.getByRole("status").textContent).toBe("登录已验证");
  });

  test.each(["请先打开登录页。", "暂时无法确认登录状态，请检查网络后重试。"])("shows unsuccessful login result: %s", async (text) => {
    const runCommand = vi.fn(async () => ({ ...defaultStatus, login_ready: false, status_message: text }));
    render(<SettingsPage busy={null} runCommand={runCommand as CommandRunner} />);
    await userEvent.click(screen.getByRole("button", { name: /检查登录/ }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe(text));
  });

  test("a failed command does not leave login checking indefinitely", async () => {
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
});
