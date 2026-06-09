// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { railwatchApi } from "../lib/railwatchApi";
import { defaultRuntimeInfo, defaultStatus, railwatchStore } from "../store/railwatchStore";
import { SettingsPage } from "./SettingsPage";
import type { CommandRunner } from "./componentTypes";

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

  test("shows local runtime data and separated maintenance actions", () => {
    const runCommand = vi.fn(async () => undefined) as CommandRunner;

    render(<SettingsPage busy={null} runCommand={runCommand} />);

    expect(screen.getByRole("heading", { name: "系统设置" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "环境健康" })).toBeTruthy();
    expect(screen.getByText("C:/RailWatch/data")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "启动步骤" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "高风险操作" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "应用更新" })).toBeNull();
    expect(screen.queryByRole("button", { name: /检查更新/ })).toBeNull();
    expect(screen.getByRole("button", { name: /清除数据/ })).toBeTruthy();

    const checkEnvironment = screen.getByRole("button", { name: /检查环境/ });
    expect(checkEnvironment).toBeTruthy();
    expect(screen.getByRole("button", { name: /下载 ChromeDriver/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /打开登录/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /检查登录/ })).toBeTruthy();
    expect(checkEnvironment.closest(".sw-danger-section")).toBeNull();

    expect(screen.getByRole("button", { name: /关闭浏览器/ })).toBeTruthy();
    const clearLocalData = screen.getByRole("button", { name: /清除数据/ });
    expect(clearLocalData).toBeTruthy();
    expect(clearLocalData.closest(".sw-danger-section")).toBeTruthy();
  });
});
