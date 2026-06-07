// @vitest-environment jsdom
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, test, vi } from "vitest";
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
    hits: [],
    notifications: [],
    activePage: "监控",
    logPaused: false,
    eventPanelVisible: true,
  });
}

describe("MonitorPage", () => {
  beforeEach(resetStore);

  test("keeps monitor controls gated by query and monitoring state", async () => {
    const user = userEvent.setup();
    const runCommand = vi.fn(async () => undefined) as CommandRunner;

    render(<MonitorPage busy={null} runCommand={runCommand} />);

    expect((screen.getByRole("button", { name: /启动监控/ }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: /停止监控/ }) as HTMLButtonElement).disabled).toBe(true);

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

    await user.click(screen.getByRole("button", { name: /停止监控/ }));

    expect(runCommand).toHaveBeenCalledWith("stopMonitor");
  });
});
