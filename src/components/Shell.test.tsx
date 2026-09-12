// @vitest-environment jsdom
import { useState } from "react";
import {
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import {
  defaultRuntimeInfo,
  defaultStatus,
  railwatchStore,
} from "../store/railwatchStore";
import { EventPanel } from "./EventPanel";
import { RAILWATCH_PAGES, ShellLayout, SidebarNav } from "./Shell";
afterEach(cleanup);

test("keeps page navigation while moving technical data out of the sidebar", async () => {
  const onPageChange = vi.fn();
  render(
    <SidebarNav
      activePage="仪表盘"
      appName="RailWatch 12306"
      onPageChange={onPageChange}
    />,
  );
  expect(RAILWATCH_PAGES.map((p) => p.name)).toEqual([
    "仪表盘",
    "行程设置",
    "购票监控",
    "系统设置",
    "关于",
  ]);
  expect(screen.getByRole("img", { name: "RailWatch 12306" })).toBeTruthy();
  expect(screen.queryByText("数据目录")).toBeNull();
  expect(
    screen.getByRole("button", { name: "仪表盘" }).getAttribute("aria-current"),
  ).toBe("page");
  await userEvent.click(screen.getByRole("button", { name: "行程设置" }));
  expect(onPageChange).toHaveBeenCalledWith("行程设置");
});

function Harness() {
  const [open, setOpen] = useState(false);
  return (
    <ShellLayout
      activePage="仪表盘"
      darkMode={false}
      eventPanel={
        <EventPanel
          onClose={() => setOpen(false)}
          onExport={vi.fn()}
          runCommand={vi.fn()}
        />
      }
      eventPanelVisible={open}
      runtime={{ ...defaultRuntimeInfo, app_version: "0.3.2" }}
      status={defaultStatus}
      onPageChange={vi.fn()}
      onToggleEventPanel={() => setOpen(!open)}
    >
      <div>任务内容</div>
    </ShellLayout>
  );
}
test("shows a consistent title, compact status bar, and collapsible navigation", async () => {
  render(<Harness />);
  expect(
    screen.getByRole("heading", { name: "仪表盘", level: 1 }),
  ).toBeTruthy();
  expect(screen.getByLabelText("系统时钟")).toBeTruthy();
  expect(screen.getByText("v0.3.2")).toBeTruthy();
  await userEvent.click(screen.getByRole("button", { name: "折叠侧栏" }));
  expect(screen.getByRole("button", { name: "展开侧栏" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "购票监控" })).toBeTruthy();
});
test("opens logs on demand, closes with Escape, and keeps filter and feed state", async () => {
  railwatchStore.setState({
    logs: [
      { id: 1, time: "12:00:00", level: "ERROR", message: "网络连接中断" },
    ],
    logPaused: false,
  });
  render(<Harness />);
  const trigger = screen.getByRole("button", { name: "显示事件日志" });
  expect(screen.queryByRole("dialog")).toBeNull();
  await userEvent.click(trigger);
  const dialog = await screen.findByRole("dialog");
  await userEvent.click(within(dialog).getByRole("tab", { name: /错误/ }));
  expect(within(dialog).getByRole("button", { name: "导出日志" })).toBeTruthy();
  await userEvent.keyboard("{Escape}");
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  await waitFor(() => expect(document.activeElement).toBe(trigger));
  railwatchStore
    .getState()
    .applyLog({ time: "12:01:00", level: "INFO", message: "后台仍在接收日志" });
  await userEvent.click(trigger);
  expect(
    screen.getByRole("tab", { name: /错误/ }).getAttribute("aria-selected"),
  ).toBe("true");
  expect(railwatchStore.getState().logs).toHaveLength(2);
});
