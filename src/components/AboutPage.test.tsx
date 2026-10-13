// @vitest-environment jsdom
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App as AntApp, ConfigProvider } from "antd";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { railwatchApi } from "../lib/railwatchApi";
import { defaultRuntimeInfo, defaultStatus, railwatchStore } from "../store/railwatchStore";
import type { UpdateRuntimeState } from "../types";
import { AboutPage } from "./AboutPage";
import { ShellLayout } from "./Shell";

const REPO_URL = "https://github.com/shyrel666/RailWatch-12306";

function renderPage() {
  return render(
    <AntApp>
      <AboutPage />
    </AntApp>,
  );
}

function resetStore() {
  railwatchStore.setState({
    runtime: {
      ...defaultRuntimeInfo,
      app_display_name: "RailWatch 12306",
      app_version: "0.3.2",
      chrome_version: "Chrome 152",
      data_dir: "C:/RailWatch/data",
      state: { ...defaultStatus },
    },
    status: { ...defaultStatus },
  });
}

describe("AboutPage", () => {
  beforeEach(() => {
    resetStore();
    vi.restoreAllMocks();
    vi.spyOn(railwatchApi, "getUpdateState").mockResolvedValue({ phase: "idle", currentVersion: "0.3.2" });
    vi.spyOn(railwatchApi, "onUpdateState").mockReturnValue(() => undefined);
  });

  afterEach(cleanup);

  test("shows the brand, version and environment", async () => {
    vi.spyOn(railwatchApi, "getAppInfo").mockResolvedValue({
      appVersion: "0.3.2",
      electronVersion: "39.8.10",
      chromeVersion: "142.0.7444.265",
      nodeVersion: "22.22.1",
      platform: "win32",
      arch: "x64",
    });

    renderPage();

    expect(screen.getByRole("img", { name: "RailWatch 12306" })).toBeTruthy();
    expect(screen.getByText("v0.3.2")).toBeTruthy();
    expect(screen.getByText("本地运行的 12306 购票助手：起售监控、自动提交、自动候补与订单跟踪。")).toBeTruthy();
    expect(screen.getByRole("button", { name: /检查更新/ })).toBeTruthy();
    expect(screen.getByText(/不是 12306 官方产品/)).toBeTruthy();

    const environment = await screen.findByLabelText("运行环境");
    for (const value of ["39.8.10", "142.0.7444.265", "22.22.1", "Windows x64"]) {
      expect(within(environment).getByText(value)).toBeTruthy();
    }
  });

  test("says so when the runtime environment cannot be read", async () => {
    vi.spyOn(railwatchApi, "getAppInfo").mockRejectedValue(new Error("no bridge"));

    renderPage();

    expect(await screen.findByText("运行环境暂不可用")).toBeTruthy();
    expect(screen.queryByLabelText("运行环境")).toBeNull();
  });

  test("opens project links through the bridge", async () => {
    vi.spyOn(railwatchApi, "getAppInfo").mockRejectedValue(new Error("no bridge"));
    const openExternal = vi.spyOn(railwatchApi, "openExternal").mockResolvedValue({ ok: true });
    const user = userEvent.setup();

    renderPage();

    await user.click(screen.getByRole("button", { name: /发布与下载/ }));

    expect(openExternal).toHaveBeenCalledWith(`${REPO_URL}/releases`);
  });

  test("macOS manual updates open the same panel before opening the release page", async () => {
    vi.spyOn(railwatchApi, "getAppInfo").mockRejectedValue(new Error("no bridge"));
    vi.spyOn(railwatchApi, "onUpdateState").mockReturnValue(() => undefined);
    const releaseUrl = `${REPO_URL}/releases/tag/v0.4.0`;
    vi.spyOn(railwatchApi, "getUpdateState").mockResolvedValue({
      phase: "available", currentVersion: "0.3.2", latestVersion: "0.4.0", installMode: "manual",
      result: { ok: true, currentVersion: "0.3.2", latestVersion: "0.4.0", hasUpdate: true, releaseName: "0.4.0",
        releaseNotes: "", publishedAt: "", releaseUrl, assets: [], source: "updater" },
    });
    const openExternal = vi.spyOn(railwatchApi, "openExternal").mockResolvedValue({ ok: true });
    const user = userEvent.setup();

    renderPage();

    const trigger = await screen.findByRole("button", { name: "查看可用更新" });
    expect(screen.getByText("发现新版本 v0.4.0，请前往发布页下载 macOS 安装包")).toBeTruthy();
    expect(screen.getByRole("status").querySelector(".lamp.wait")).toBeTruthy();
    await user.click(trigger);
    const dialog = await screen.findByRole("dialog", { name: "软件更新" });
    expect(openExternal).not.toHaveBeenCalled();
    expect(within(dialog).getByText("前往发布页下载 macOS 安装包。")).toBeTruthy();
    await user.click(within(dialog).getByRole("button", { name: "前往下载" }));
    expect(openExternal).toHaveBeenCalledExactlyOnceWith(releaseUrl);
  });

  test("shares downloaded updates and installation-block reasons between the sidebar and About panel", async () => {
    const user = userEvent.setup();
    const reason = "当前存在活动任务，更新已推迟。";
    vi.spyOn(railwatchApi, "getAppInfo").mockRejectedValue(new Error("no bridge"));
    const getUpdateState = vi.spyOn(railwatchApi, "getUpdateState").mockResolvedValue({
      phase: "downloaded", currentVersion: "0.3.2", latestVersion: "0.4.0", downloadPercent: 100,
    });
    const installUpdate = vi.spyOn(railwatchApi, "installUpdate").mockResolvedValue({ ok: false, error: reason });
    render(
      <ConfigProvider theme={{ token: { motion: false } }}>
        <AntApp>
          <ShellLayout
            activePage="关于" darkMode={false} eventPanel={null} eventPanelVisible={false}
            runtime={{ ...defaultRuntimeInfo, app_version: "0.3.2" }} status={{ ...defaultStatus }}
            onPageChange={vi.fn()} onToggleEventPanel={vi.fn()}
          ><AboutPage /></ShellLayout>
        </AntApp>
      </ConfigProvider>,
    );

    const sidebar = screen.getByRole("complementary");
    const about = screen.getByRole("region", { name: "应用信息" });
    const sidebarTrigger = await within(sidebar).findByRole("button", { name: "查看已下载更新" });
    await within(about).findByRole("button", { name: "查看已下载更新" });
    expect(getUpdateState).toHaveBeenCalledOnce();

    await user.click(sidebarTrigger);
    const sidebarDialog = await screen.findByRole("dialog", { name: "软件更新" });
    await user.click(within(sidebarDialog).getByRole("button", { name: "立即重启安装" }));
    expect((await within(sidebarDialog).findByRole("alert")).textContent).toContain(reason);
    expect(within(about).getByRole("status").textContent).toContain(reason);
    await user.click(within(sidebarDialog).getByRole("button", { name: "收起更新面板" }));
    // The sidebar popover stays mounted until its leave animation ends.
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "软件更新" })).toBeNull());

    await user.click(within(about).getByRole("button", { name: "查看已下载更新" }));
    const aboutDialog = await screen.findByRole("dialog", { name: "软件更新" });
    expect(within(aboutDialog).getByRole("alert").textContent).toContain(reason);
    expect(within(aboutDialog).getByRole("button", { name: "立即重启安装" })).toBeTruthy();
    expect(installUpdate).toHaveBeenCalledOnce();
  });

  test("keeps the open About update panel and its focus when the download completes", async () => {
    const user = userEvent.setup();
    const listeners = new Set<(state: UpdateRuntimeState) => void>();
    vi.spyOn(railwatchApi, "onUpdateState").mockImplementation(callback => {
      listeners.add(callback);
      return () => { listeners.delete(callback); };
    });
    vi.spyOn(railwatchApi, "getAppInfo").mockRejectedValue(new Error("no bridge"));
    vi.spyOn(railwatchApi, "getUpdateState").mockResolvedValue({
      phase: "downloading", currentVersion: "0.3.2", latestVersion: "0.4.0", downloadPercent: 67,
    });
    const taskActivity = vi.spyOn(railwatchApi, "command").mockImplementation(async () => ({
      state: "idle", run_id: null, operation: null, unresolved_order: false, checked_at: 1,
    }) as never);
    const installUpdate = vi.spyOn(railwatchApi, "installUpdate");
    render(
      <ConfigProvider theme={{ token: { motion: false } }}>
        <AntApp>
          <ShellLayout
            activePage="关于" darkMode={false} eventPanel={null} eventPanelVisible={false}
            runtime={{ ...defaultRuntimeInfo, app_version: "0.3.2" }} status={{ ...defaultStatus }}
            onPageChange={vi.fn()} onToggleEventPanel={vi.fn()}
          ><AboutPage /></ShellLayout>
        </AntApp>
      </ConfigProvider>,
    );

    const about = screen.getByRole("region", { name: "应用信息" });
    const aboutTrigger = await within(about).findByRole("button", { name: "查看更新进度" });
    await user.click(aboutTrigger);
    const dialog = await screen.findByRole("dialog", { name: "软件更新" });
    const closeButton = within(dialog).getByRole("button", { name: "收起更新面板" });
    closeButton.focus();

    await act(async () => {
      const completed: UpdateRuntimeState = {
        phase: "downloaded", currentVersion: "0.3.2", latestVersion: "0.4.0", downloadPercent: 100,
      };
      listeners.forEach(listener => listener(completed));
    });

    expect(taskActivity).toHaveBeenCalledExactlyOnceWith("taskActivity");
    expect(screen.getAllByRole("dialog", { name: "软件更新" })).toEqual([dialog]);
    expect(aboutTrigger.getAttribute("aria-expanded")).toBe("true");
    const sidebarTrigger = within(screen.getByRole("complementary")).getByRole("button", { name: "查看已下载更新" });
    expect(sidebarTrigger.getAttribute("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(closeButton);
    expect(within(dialog).getByRole("button", { name: "立即重启安装" })).toBeTruthy();
    expect(installUpdate).not.toHaveBeenCalled();
  });

  test("reports a blocked link instead of failing silently", async () => {
    vi.spyOn(railwatchApi, "getAppInfo").mockRejectedValue(new Error("no bridge"));
    vi.spyOn(railwatchApi, "openExternal").mockResolvedValue({ ok: false, error: "blocked" });
    const user = userEvent.setup();

    renderPage();

    await user.click(screen.getByRole("button", { name: /问题反馈/ }));

    expect(await screen.findByText("无法打开链接，请在浏览器中手动访问。")).toBeTruthy();
  });
});
