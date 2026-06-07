// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { defaultConfig, defaultRuntimeInfo, defaultStatus, railwatchStore } from "../store/railwatchStore";
import { TripSetupPage } from "./TripSetupPage";
import type { CommandRunner, ConfirmDialog } from "./componentTypes";

function resetStore() {
  railwatchStore.setState({
    runtime: { ...defaultRuntimeInfo, state: { ...defaultStatus } },
    status: { ...defaultStatus },
    config: { ...defaultConfig, train_code: "" },
    logs: [],
    results: [],
    hits: [],
    notifications: [],
    activePage: "行程设置",
    logPaused: false,
    eventPanelVisible: true,
  });
}

describe("TripSetupPage", () => {
  beforeEach(resetStore);
  afterEach(cleanup);

  test("normalizes train code input and keeps automation guarded by confirmation", async () => {
    const user = userEvent.setup();
    const confirm = vi.fn(async () => false) as ConfirmDialog;
    const runCommand = vi.fn(async () => undefined) as CommandRunner;

    render(<TripSetupPage busy={null} confirm={confirm} runCommand={runCommand} />);

    await user.type(screen.getByLabelText("车次"), "g101");

    expect(railwatchStore.getState().config.train_code).toBe("G101");

    const autoSubmitSwitch = screen.getByRole("switch", { name: /自动提交关闭.*开启时需要确认/ });
    await user.click(autoSubmitSwitch);

    expect(confirm).toHaveBeenCalledWith("启用自动提交", expect.stringContaining("自动提交"));
    expect(railwatchStore.getState().config.auto_submit).toBe(false);
    expect(runCommand).not.toHaveBeenCalled();
  });

  test("keeps trip setup as a form workspace without dashboard workflow", () => {
    const confirm = vi.fn(async () => false) as ConfirmDialog;
    const runCommand = vi.fn(async () => undefined) as CommandRunner;

    render(<TripSetupPage busy={null} confirm={confirm} runCommand={runCommand} />);

    expect(screen.getByRole("heading", { name: "行程设置" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "安全确认" })).toBeTruthy();
    expect(screen.getByLabelText("出发")).toBeTruthy();
    expect(screen.getByLabelText("到达")).toBeTruthy();
    expect(screen.getByText("自动提交关闭")).toBeTruthy();
    expect(screen.getByText("候补排队关闭")).toBeTruthy();
    expect(screen.getByText("开启时需要确认；开启后命中车票可能自动进入订单流程。")).toBeTruthy();
    expect(screen.getByText("开启时需要确认；开启后无票时可能自动提交候补。")).toBeTruthy();
    expect(screen.queryByText(/进入订单流程前必须确认|排队前必须确认/)).toBeNull();
    expect(screen.getByRole("switch", { name: "定时启动" })).toBeTruthy();
    expect(screen.getByRole("switch", { name: "保持会话" })).toBeTruthy();
    expect(screen.getByRole("switch", { name: "智能轮询" })).toBeTruthy();
    expect(screen.queryByRole("list", { name: "监控流程" })).toBeNull();
  });
});
