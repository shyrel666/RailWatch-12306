// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { isoDaysFromToday, todayIso } from "../lib/tripDate";
import {
  defaultConfig,
  defaultRuntimeInfo,
  defaultStatus,
  railwatchStore,
} from "../store/railwatchStore";
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

  test("priority applies a complete preset, persists on remount, and leaves trip choices intact", async () => {
    const user = userEvent.setup();
    railwatchStore.setState({ config: { ...defaultConfig, interval: 20, query_timeout: 70,
      smart_rate: false, keep_alive: false, seat_prefer: "靠窗优先", train_code: "G101" } });
    const renderPage = () => render(<TripSetupPage busy={null} confirm={async () => false}
      runCommand={(async () => undefined) as CommandRunner} />);
    let page = renderPage();
    await user.click(screen.getByText("查询策略", { selector: "h2" }));
    await user.click(screen.getByRole("button", { name: "速度优先" }));
    expect(railwatchStore.getState().config).toMatchObject({ query_priority: "speed", request_mode: "fast",
      interval: 3, query_timeout: 20, smart_rate: true, keep_alive: true,
      seat_prefer: "靠窗优先", train_code: "G101", auto_submit: false, auto_alternate: false });
    expect(screen.getByText("3.0 ~ 3.6 秒")).toBeTruthy();
    await user.click(screen.getByLabelText("增加超时时间"));
    expect(screen.getByText(/已自定义/)).toBeTruthy();
    page.unmount();
    page = renderPage();
    await user.click(screen.getByText("查询策略", { selector: "h2" }));
    expect(screen.getByRole("button", { name: "速度优先" }).getAttribute("aria-pressed")).toBe("true");
    expect(railwatchStore.getState().config.query_timeout).toBe(21);
    await user.click(screen.getByRole("button", { name: "成功率优先" }));
    expect(railwatchStore.getState().config).toMatchObject({ query_priority: "reliability", request_mode: "conservative",
      interval: 6, query_timeout: 40, smart_rate: true, keep_alive: true });
    expect(screen.getByText("5.0 ~ 7.2 秒")).toBeTruthy();
  });

  test("restoring saved settings updates the selected priority and request mode", async () => {
    const user = userEvent.setup();
    const saved = { ...defaultConfig, query_priority: "speed" as const, request_mode: "balanced" as const,
      interval: 7.5, query_timeout: 51 };
    render(<TripSetupPage busy={null} confirm={async () => false}
      runCommand={(async () => saved) as CommandRunner} />);
    await user.click(screen.getByRole("button", { name: "恢复上次保存" }));
    await user.click(screen.getByText("查询策略", { selector: "h2" }));
    expect(screen.getByRole("button", { name: "速度优先" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText("均衡模式")).toBeTruthy();
    expect(screen.getByText(/已自定义/)).toBeTruthy();
    expect(railwatchStore.getState().config.query_timeout).toBe(51);
  });

  test("normalizes train code input and keeps automation guarded by confirmation", async () => {
    const user = userEvent.setup();
    const confirm = vi.fn(async () => false) as ConfirmDialog;
    const runCommand = vi.fn(async () => undefined) as CommandRunner;

    render(
      <TripSetupPage busy={null} confirm={confirm} runCommand={runCommand} />,
    );

    await user.type(screen.getByLabelText("车次"), "g101");

    expect(railwatchStore.getState().config.train_code).toBe("G101");

    await user.click(screen.getByText("自动化", { selector: "h2" }));
    const autoSubmitSwitch = screen.getByRole("switch", {
      name: /自动提交关闭.*开启时需要确认/,
    });
    await user.click(autoSubmitSwitch);

    expect(confirm).toHaveBeenCalledWith(
      "启用自动提交",
      expect.stringContaining("自动提交"),
    );
    expect(railwatchStore.getState().config.auto_submit).toBe(false);
    expect(runCommand).not.toHaveBeenCalled();
  });

  test("常用车次 merges every preset code", async () => {
    const user = userEvent.setup();
    railwatchStore.setState({ config: { ...defaultConfig, train_code: "" } });

    render(
      <TripSetupPage
        busy={null}
        confirm={(async () => false) as ConfirmDialog}
        runCommand={(async () => undefined) as CommandRunner}
      />,
    );

    await user.click(screen.getByRole("button", { name: "常用车次" }));

    const codes = railwatchStore
      .getState()
      .config.train_code.split(/[,，、\s]+/)
      .filter(Boolean);
    expect(codes).toEqual(
      expect.arrayContaining(["G1", "G3", "G17", "D313", "D321"]),
    );
  });

  test("groups all preferences without dashboard workflow", async () => {
    const confirm = vi.fn(async () => false) as ConfirmDialog;
    const runCommand = vi.fn(async () => undefined) as CommandRunner;

    render(
      <TripSetupPage busy={null} confirm={confirm} runCommand={runCommand} />,
    );

    expect(screen.getByRole("heading", { name: "路线与乘客" })).toBeTruthy();
    expect(screen.getByText("配置查询条件与监控策略")).toBeTruthy();
    expect(screen.getByRole("button", { name: "恢复上次保存" })).toBeTruthy();
    expect(screen.getByLabelText("出发站")).toBeTruthy();
    expect(screen.getByLabelText("到达站")).toBeTruthy();
    expect(screen.getByLabelText("出发日期")).toBeTruthy();
    expect(screen.getByRole("group", { name: "日期范围" })).toBeTruthy();
    expect(screen.getByRole("group", { name: "席别" })).toBeTruthy();
    await userEvent.click(screen.getByText("查询策略", { selector: "h2" }));
    await userEvent.click(screen.getByText("定时启动", { selector: "h2" }));
    await userEvent.click(screen.getByText("自动化", { selector: "h2" }));
    expect(screen.getByRole("group", { name: "优先级" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "保存配置" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "查询余票" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "开始监控" })).toBeNull();
    expect(screen.queryByRole("button", { name: /高级选项/ })).toBeNull();
    expect(screen.queryByRole("list", { name: "监控流程" })).toBeNull();
    expect(screen.queryByText("高级选项")).toBeNull();
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

    render(
      <TripSetupPage busy={null} confirm={confirm} runCommand={runCommand} />,
    );

    await user.click(
      screen.getByRole("button", { name: "交换出发站与到达站" }),
    );

    expect(railwatchStore.getState().config.from_station_cn).toBe("上海");
    expect(railwatchStore.getState().config.to_station_cn).toBe("北京");
  });

  test("writes query timeout and supported date range into backend config shape", async () => {
    const user = userEvent.setup();
    const confirm = vi.fn(async () => false) as ConfirmDialog;
    const runCommand = vi.fn(async () => undefined) as CommandRunner;

    render(
      <TripSetupPage busy={null} confirm={confirm} runCommand={runCommand} />,
    );

    await user.click(screen.getByRole("button", { name: "±2天" }));
    await user.click(screen.getByText("查询策略", { selector: "h2" }));
    await user.click(screen.getByLabelText("增加超时时间"));

    expect(railwatchStore.getState().config.date_range).toBe("±2天");
    expect(railwatchStore.getState().config.query_timeout).toBe(41);
    expect(screen.queryByRole("button", { name: "自定义" })).toBeNull();
  });

  test("date picker cannot start before today and shows no hint for a valid date", () => {
    railwatchStore.setState({
      config: { ...defaultConfig, date: isoDaysFromToday(3) },
    });

    render(
      <TripSetupPage
        busy={null}
        confirm={(async () => false) as ConfirmDialog}
        runCommand={(async () => undefined) as CommandRunner}
      />,
    );

    expect(screen.getByLabelText("出发日期").getAttribute("min")).toBe(
      todayIso(),
    );
    expect(screen.queryByText(/出发日期已过去/)).toBeNull();
    expect(screen.queryByText(/预售期/)).toBeNull();
  });

  test("saving an expired departure date requires confirmation and respects a decline", async () => {
    const user = userEvent.setup();
    const confirm = vi.fn(async () => false) as ConfirmDialog;
    const runCommand = vi.fn(async () => undefined) as CommandRunner;
    railwatchStore.setState({
      config: { ...defaultConfig, date: "2020-01-01" },
    });

    render(
      <TripSetupPage busy={null} confirm={confirm} runCommand={runCommand} />,
    );

    expect(screen.getByText(/出发日期已过去/)).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "保存配置" }));

    expect(confirm).toHaveBeenCalledWith(
      "出发日期已过期",
      expect.stringContaining("2020-01-01"),
    );
    expect(runCommand).not.toHaveBeenCalled();
  });

  test("saving an expired departure date proceeds after explicit confirmation", async () => {
    const user = userEvent.setup();
    const confirm = vi.fn(async () => true) as ConfirmDialog;
    const runCommand = vi.fn(async () => undefined) as CommandRunner;
    railwatchStore.setState({
      config: { ...defaultConfig, date: "2020-01-01" },
    });

    render(
      <TripSetupPage busy={null} confirm={confirm} runCommand={runCommand} />,
    );

    await user.click(screen.getByRole("button", { name: "保存配置" }));

    expect(confirm).toHaveBeenCalledTimes(1);
    expect(runCommand).toHaveBeenCalledWith(
      "saveConfig",
      { config: expect.objectContaining({ date: "2020-01-01" }) },
      "设置已保存",
    );
  });

  test("saving a valid date does not trigger the expired-date confirmation", async () => {
    const user = userEvent.setup();
    const confirm = vi.fn(async () => false) as ConfirmDialog;
    const runCommand = vi.fn(async () => undefined) as CommandRunner;
    railwatchStore.setState({
      config: { ...defaultConfig, date: isoDaysFromToday(3) },
    });

    render(
      <TripSetupPage busy={null} confirm={confirm} runCommand={runCommand} />,
    );

    await user.click(screen.getByRole("button", { name: "保存配置" }));

    expect(confirm).not.toHaveBeenCalled();
    expect(runCommand).toHaveBeenCalledWith(
      "saveConfig",
      { config: expect.anything() },
      "设置已保存",
    );
  });
});
