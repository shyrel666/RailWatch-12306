// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, test, vi } from "vitest";
import { defaultRuntimeInfo, defaultStatus } from "../store/railwatchStore";
import { RAILWATCH_PAGES, ShellLayout, SidebarNav } from "./Shell";

afterEach(cleanup);

describe("SidebarNav", () => {
  test("keeps stable page names and reports navigation clicks", async () => {
    const user = userEvent.setup();
    const onPageChange = vi.fn();

    expect(RAILWATCH_PAGES.map((page) => page.name)).toEqual(["仪表盘", "行程设置", "购票监控", "系统设置"]);

    render(
      <SidebarNav
        activePage="仪表盘"
        appName="RailWatch 12306"
        appVersion="0.1.0"
        dataDir="D:/RailWatch/data"
        dataDirWritable
        dataDirFreeBytes={128_600_000_000}
        onPageChange={onPageChange}
      />,
    );

    expect(screen.getByText("RailWatch 12306")).toBeTruthy();
    expect(screen.getByText("D:/RailWatch/data")).toBeTruthy();
    expect(screen.getByText("v0.1.0")).toBeTruthy();
    expect(screen.getByText("119.8 GB")).toBeTruthy();
    expect(screen.getByLabelText("系统时钟")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: /行程设置/ }));

    expect(onPageChange).toHaveBeenCalledWith("行程设置");
  });
});

describe("ShellLayout", () => {
  test("renders the desktop shell and can toggle the event panel", async () => {
    const user = userEvent.setup();
    const onExportLog = vi.fn();
    const onThemeChange = vi.fn();
    const onToggleEventPanel = vi.fn();

    const { container } = render(
      <ShellLayout
        activePage="购票监控"
        darkMode
        eventPanel={<aside>事件面板</aside>}
        eventPanelVisible
        runtime={{
          ...defaultRuntimeInfo,
          app_display_name: "RailWatch 12306",
          app_version: "0.1.0",
          data_dir: "D:/RailWatch/data",
          data_dir_writable: true,
          data_dir_free_bytes: 128_600_000_000,
          network_ok: true,
          network_label: "正常",
          railway_ok: true,
          railway_label: "正常",
          proxy_configured: false,
          proxy_label: "未配置",
        }}
        status={{ ...defaultStatus, summary: "查询已解析", status_message: "已解析 53 行查询结果", phase: "query_ready" }}
        onPageChange={vi.fn()}
        onExportLog={onExportLog}
        onThemeChange={onThemeChange}
        onToggleEventPanel={onToggleEventPanel}
      >
        <div>监控内容</div>
      </ShellLayout>,
    );

    const workspace = container.querySelector("main.workspace");
    expect(workspace?.classList.contains("monitor-workspace-shell")).toBe(true);
    expect(screen.queryByRole("heading", { name: "购票监控", level: 1 })).toBeNull();
    expect(screen.getByText("运行")).toBeTruthy();
    expect(screen.getByText("查询就绪")).toBeTruthy();
    expect(screen.getByText("监控内容")).toBeTruthy();
    expect(screen.getByText("事件面板")).toBeTruthy();
    expect(screen.getByRole("button", { name: "切换到明亮主题" })).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "切换到明亮主题" }));

    expect(onThemeChange).toHaveBeenCalledWith(false);

    await user.click(screen.getByRole("button", { name: "隐藏事件日志" }));

    expect(onToggleEventPanel).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "导出日志" }));

    expect(onExportLog).toHaveBeenCalledTimes(1);
  });

  test("hides the duplicate topbar on trip setup", () => {
    render(
      <ShellLayout
        activePage="行程设置"
        darkMode
        eventPanel={null}
        eventPanelVisible
        runtime={{ ...defaultRuntimeInfo, app_display_name: "RailWatch 12306", data_dir: "D:/RailWatch/data" }}
        status={{ ...defaultStatus, summary: "就绪" }}
        onPageChange={vi.fn()}
        onExportLog={vi.fn()}
        onThemeChange={vi.fn()}
        onToggleEventPanel={vi.fn()}
      >
        <div>行程设置内容</div>
      </ShellLayout>,
    );

    expect(screen.queryByRole("heading", { name: "行程设置", level: 1 })).toBeNull();
    expect(screen.queryByRole("toolbar", { name: "顶部操作" })).toBeNull();
    expect(screen.getByText("行程设置内容")).toBeTruthy();
  });
});
