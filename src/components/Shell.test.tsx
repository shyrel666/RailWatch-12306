// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test, vi } from "vitest";
import { defaultRuntimeInfo, defaultStatus } from "../store/railwatchStore";
import { RAILWATCH_PAGES, ShellLayout, SidebarNav } from "./Shell";

describe("SidebarNav", () => {
  test("keeps stable page names and reports navigation clicks", async () => {
    const user = userEvent.setup();
    const onPageChange = vi.fn();

    expect(RAILWATCH_PAGES.map((page) => page.name)).toEqual(["仪表盘", "行程设置", "监控", "设置"]);

    render(
      <SidebarNav
        activePage="仪表盘"
        appName="RailWatch 12306"
        dataDir="D:/RailWatch/data"
        phase="idle"
        onPageChange={onPageChange}
      />,
    );

    expect(screen.getByText("RailWatch 12306")).toBeTruthy();
    expect(screen.getByText("D:/RailWatch/data")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: /行程设置/ }));

    expect(onPageChange).toHaveBeenCalledWith("行程设置");
  });
});

describe("ShellLayout", () => {
  test("renders the desktop shell and can toggle the event panel", async () => {
    const user = userEvent.setup();
    const onToggleEventPanel = vi.fn();

    render(
      <ShellLayout
        activePage="监控"
        darkMode
        eventPanel={<aside>事件面板</aside>}
        eventPanelVisible
        runtime={{ ...defaultRuntimeInfo, app_display_name: "RailWatch 12306", data_dir: "D:/RailWatch/data" }}
        status={{ ...defaultStatus, summary: "查询已解析", status_message: "就绪" }}
        onPageChange={vi.fn()}
        onToggleEventPanel={onToggleEventPanel}
      >
        <div>监控内容</div>
      </ShellLayout>,
    );

    expect(screen.getByRole("heading", { name: "监控" })).toBeTruthy();
    expect(screen.getByText("查询已解析")).toBeTruthy();
    expect(screen.getByText("监控内容")).toBeTruthy();
    expect(screen.getByText("事件面板")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "隐藏事件" }));

    expect(onToggleEventPanel).toHaveBeenCalledTimes(1);
  });
});
