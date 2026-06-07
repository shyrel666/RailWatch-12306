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
      { time: "09:00:01", level: "INFO", message: "环境检查完成" },
      { time: "09:00:02", level: "ERROR", message: "登录状态失效" },
      { time: "09:00:03", level: "WARN", message: "刷新间隔偏低" },
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

  test("surfaces live feed feedback and puts errors first", async () => {
    const user = userEvent.setup();
    const runCommand = vi.fn(async () => undefined) as CommandRunner;
    const onClose = vi.fn();

    render(<EventPanel runCommand={runCommand} onClose={onClose} />);

    expect(screen.getByText("当前显示 3 条")).toBeTruthy();

    const feed = screen.getByRole("feed", { name: "事件流" });
    const entries = within(feed).getAllByRole("article");

    expect(entries[0].textContent).toContain("ERROR");
    expect(entries[0].textContent).toContain("登录状态失效");

    const pauseButton = screen.getByRole("button", { name: "暂停滚动" });
    expect(pauseButton.getAttribute("aria-pressed")).toBe("false");

    await user.click(pauseButton);

    expect(screen.getByText("事件流已暂停")).toBeTruthy();
    expect(screen.getByRole("button", { name: "恢复滚动" }).getAttribute("aria-pressed")).toBe("true");
  });

  test("offers an in-panel close action for drawer layouts", async () => {
    const user = userEvent.setup();
    const runCommand = vi.fn(async () => undefined) as CommandRunner;
    const onClose = vi.fn();

    render(<EventPanel runCommand={runCommand} onClose={onClose} />);

    await user.click(screen.getByRole("button", { name: "隐藏事件面板" }));

    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
