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
    status: { ...defaultStatus, query_ready: true },
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

  test("renders the reference trip setup card without dashboard workflow", () => {
    const confirm = vi.fn(async () => false) as ConfirmDialog;
    const runCommand = vi.fn(async () => undefined) as CommandRunner;

    render(<TripSetupPage busy={null} confirm={confirm} runCommand={runCommand} />);

    expect(screen.getByRole("heading", { name: "行程设置" })).toBeTruthy();
    expect(screen.getByText("配置查询条件与监控策略")).toBeTruthy();
    expect(screen.getByRole("button", { name: "恢复上次保存" })).toBeTruthy();
    expect(screen.getByLabelText("出发站")).toBeTruthy();
    expect(screen.getByLabelText("到达站")).toBeTruthy();
    expect(screen.getByLabelText("出发日期")).toBeTruthy();
    expect(screen.getByRole("group", { name: "日期范围" })).toBeTruthy();
    expect(screen.getByRole("group", { name: "席别" })).toBeTruthy();
    expect(screen.getByRole("group", { name: "优先级" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "保存配置" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "分析" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "开始监控" })).toBeNull();
    expect(screen.queryByRole("button", { name: /高级选项/ })).toBeNull();
    expect(screen.queryByRole("list", { name: "监控流程" })).toBeNull();
    expect(screen.getByText("高级选项")).toBeTruthy();
    expect(screen.getByText("自动提交关闭")).toBeTruthy();
    expect(screen.getByText("候补排队关闭")).toBeTruthy();
    expect(screen.getByRole("switch", { name: "定时启动" })).toBeTruthy();
    expect(screen.getByRole("switch", { name: "保持会话" })).toBeTruthy();
    expect(screen.getByRole("switch", { name: "智能轮询" })).toBeTruthy();
  });

  test("swaps departure and arrival stations", async () => {
    const user = userEvent.setup();
    const confirm = vi.fn(async () => false) as ConfirmDialog;
    const runCommand = vi.fn(async () => undefined) as CommandRunner;

    render(<TripSetupPage busy={null} confirm={confirm} runCommand={runCommand} />);

    await user.click(screen.getByRole("button", { name: "交换出发站与到达站" }));

    expect(railwatchStore.getState().config.from_station_cn).toBe("上海");
    expect(railwatchStore.getState().config.to_station_cn).toBe("北京");
  });

  test("writes query timeout and supported date range into backend config shape", async () => {
    const user = userEvent.setup();
    const confirm = vi.fn(async () => false) as ConfirmDialog;
    const runCommand = vi.fn(async () => undefined) as CommandRunner;

    render(<TripSetupPage busy={null} confirm={confirm} runCommand={runCommand} />);

    await user.click(screen.getByRole("button", { name: "±2天" }));
    await user.click(screen.getByLabelText("增加超时时间"));

    expect(railwatchStore.getState().config.date_range).toBe("±2天");
    expect(railwatchStore.getState().config.query_timeout).toBe(41);
    expect(screen.queryByRole("button", { name: "自定义" })).toBeNull();
  });
});
