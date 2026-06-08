// @vitest-environment jsdom
import { act, cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { defaultConfig, defaultRuntimeInfo, defaultStatus, railwatchStore } from "../store/railwatchStore";
import { MonitorPage } from "./MonitorPage";
import type { CommandRunner } from "./componentTypes";

function resetStore() {
  railwatchStore.setState({
    runtime: { ...defaultRuntimeInfo, state: { ...defaultStatus } },
    status: { ...defaultStatus },
    config: { ...defaultConfig, train_code: "G101" },
    logs: [],
    results: [],
    monitorLoops: 0,
    hits: [],
    notifications: [],
    lastHumanAction: null,
    activePage: "购票监控",
    logPaused: false,
    eventPanelVisible: true,
  });
}

describe("MonitorPage", () => {
  beforeEach(resetStore);
  afterEach(cleanup);

  test("keeps monitor controls gated by query and monitoring state", async () => {
    const user = userEvent.setup();
    const runCommand = vi.fn(async () => undefined) as CommandRunner;

    render(<MonitorPage busy={null} runCommand={runCommand} />);

    expect((screen.getByRole("button", { name: /启动监控/ }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: /停止/ }) as HTMLButtonElement).disabled).toBe(true);

    act(() => {
      railwatchStore.setState({
        status: { ...defaultStatus, query_ready: true, monitoring: false, summary: "查询已解析" },
      });
    });

    await user.click(screen.getByRole("button", { name: /启动监控/ }));

    expect(runCommand).toHaveBeenCalledWith("startMonitor", { config: expect.objectContaining({ train_code: "G101" }) });

    act(() => {
      railwatchStore.setState({
        status: { ...defaultStatus, query_ready: true, monitoring: true, summary: "监控中" },
      });
    });

    expect((screen.getByRole("button", { name: /启动监控/ }) as HTMLButtonElement).disabled).toBe(true);

    await user.click(screen.getByRole("button", { name: /停止/ }));

    expect(runCommand).toHaveBeenCalledWith("stopMonitor");
  });

  test("surfaces and dismisses a human-action handoff banner", async () => {
    const user = userEvent.setup();

    act(() => {
      railwatchStore.setState({
        lastHumanAction: {
          title: "需要人工操作",
          message: "候补需要人工核验，请在浏览器中完成。",
          train_code: "G101",
        },
      });
    });

    const { container } = render(<MonitorPage busy={null} runCommand={(async () => undefined) as CommandRunner} />);

    expect(screen.getByText("候补需要人工核验，请在浏览器中完成。")).toBeTruthy();

    const closeButton = container.querySelector(".ant-alert-close-icon");
    expect(closeButton).not.toBeNull();
    await user.click(closeButton as HTMLElement);

    expect(railwatchStore.getState().lastHumanAction).toBeNull();
    expect(screen.queryByText("候补需要人工核验，请在浏览器中完成。")).toBeNull();
  });

  test("shows the backend loop count as the query count", () => {
    act(() => {
      railwatchStore.setState({
        status: { ...defaultStatus, query_ready: true, monitoring: true },
        monitorLoops: 12,
        results: [{ train: "G55", raw: "G55 北京 上海 二等座 有" }],
      });
    });

    render(<MonitorPage busy={null} runCommand={(async () => undefined) as CommandRunner} />);

    expect(screen.getByText("12")).toBeTruthy();
    expect(screen.getByText("G55")).toBeTruthy();
  });
});
