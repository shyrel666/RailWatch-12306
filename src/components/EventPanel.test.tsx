// @vitest-environment jsdom
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { defaultConfig, defaultRuntimeInfo, defaultStatus, railwatchStore } from "../store/railwatchStore";
import { EventPanel } from "./EventPanel";
import type { CommandRunner } from "./componentTypes";

function resetStore() {
  railwatchStore.setState({
    runtime: { ...defaultRuntimeInfo, state: { ...defaultStatus } },
    status: { ...defaultStatus },
    config: { ...defaultConfig },
    logs: [
      { time: "09:00:01", level: "INFO", message: "环境检查：本地环境一切正常" },
      { time: "09:00:02", level: "ERROR", message: "登录状态失效" },
      { time: "09:00:03", level: "WARN", message: "刷新间隔偏低：建议提高到 5 秒" },
    ],
    results: [],
    hits: [],
    notifications: [],
    activePage: "仪表盘",
    logPaused: false,
    eventPanelVisible: true,
  });
}

describe("EventPanel", () => {
  beforeEach(resetStore);
  afterEach(cleanup);

  test("surfaces live feed feedback with newest events first", async () => {
    const user = userEvent.setup();
    const runCommand = vi.fn(async () => undefined) as CommandRunner;
    const onClose = vi.fn();

    render(<EventPanel runCommand={runCommand} onClose={onClose} />);

    const feed = screen.getByRole("feed", { name: "事件流" });
    const entries = within(feed).getAllByRole("article");

    expect(entries[0].textContent).toContain("刷新间隔偏低");
    expect(entries[2].textContent).toContain("环境检查");

    await user.click(screen.getByRole("button", { name: "清空事件" }));

    expect(runCommand).toHaveBeenCalledWith("clearLog");
  });

  test("keeps export out of the event panel so the feed owns the footer space", async () => {
    const runCommand = vi.fn(async () => undefined) as CommandRunner;

    render(<EventPanel runCommand={runCommand} onClose={vi.fn()} />);

    expect(screen.queryByRole("button", { name: "导出日志" })).toBeNull();
    expect(screen.queryByRole("button", { name: "隐藏事件面板" })).toBeNull();
  });

  test("shows a clear empty state when no events are available", () => {
    const runCommand = vi.fn(async () => undefined) as CommandRunner;
    railwatchStore.setState({ logs: [] });

    render(<EventPanel runCommand={runCommand} onClose={vi.fn()} />);

    expect(screen.getByText("暂无事件")).toBeTruthy();
    expect(screen.getByText("运行日志会在这里按时间倒序显示。")).toBeTruthy();
  });

  test("does not duplicate plain log messages without a colon separator", () => {
    const runCommand = vi.fn(async () => undefined) as CommandRunner;
    railwatchStore.setState({
      logs: [{ time: "19:33:44", level: "INFO", message: "正在检查 Python、Selenium 和 ChromeDriver..." }],
    });

    render(<EventPanel runCommand={runCommand} onClose={vi.fn()} />);

    const feed = screen.getByRole("feed", { name: "事件流" });
    const entry = within(feed).getByRole("article");

    expect(within(entry).getByText("环境检查")).toBeTruthy();
    expect(within(entry).getAllByText(/正在检查 Python、Selenium 和 ChromeDriver/)).toHaveLength(1);
  });
});
