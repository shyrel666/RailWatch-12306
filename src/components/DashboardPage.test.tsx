// @vitest-environment jsdom
import { act, cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, test } from "vitest";
import { isoDaysFromToday } from "../lib/tripDate";
import {
  defaultConfig,
  defaultRuntimeInfo,
  defaultStatus,
  railwatchStore,
} from "../store/railwatchStore";
import { DashboardPage } from "./DashboardPage";

function resetStore() {
  railwatchStore.setState({
    rehearsalEnabled: false,
    runtime: { ...defaultRuntimeInfo, state: { ...defaultStatus } },
    status: { ...defaultStatus },
    config: { ...defaultConfig },
    logs: [],
    results: [],
    monitorLoops: 0,
    hits: [],
    notifications: [],
    activePage: "仪表盘",
    logPaused: false,
    lastHumanAction: null,
    eventPanelVisible: true,
  });
}

describe("DashboardPage", () => {
  beforeEach(resetStore);
  afterEach(cleanup);

  test("shows one trip summary and sends the next action to environment setup", async () => {
    render(<DashboardPage />);
    expect(screen.getAllByLabelText("当前行程")).toHaveLength(1);
    expect(screen.queryByText("站点范围")).toBeNull();
    expect(screen.queryByText("请求模式")).toBeNull();
    expect(screen.queryByLabelText("自动化状态")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "检查环境" }));
    expect(railwatchStore.getState().activePage).toBe("系统设置");
    expect(railwatchStore.getState().pageSection).toBe("settings-environment");
  });

  test.each([
    { environmentReady: false, title: "检查运行环境", label: "检查环境", section: "settings-environment", board: "等待环境检查" },
    { environmentReady: true, title: "登录 12306", label: "前往登录", section: "settings-login", board: "等待登录" },
  ])("a login check without a browser returns to $section", async ({ environmentReady, title, label, section, board }) => {
    railwatchStore.setState({ status: {
      ...defaultStatus,
      phase: "error",
      risk_level: "warning",
      environment_ready: environmentReady,
      status_message: "请先打开登录页。",
      error_message: "请先打开登录页。",
    } });
    render(<DashboardPage />);

    expect(screen.getByRole("heading", { name: title })).toBeTruthy();
    expect(within(screen.getByLabelText("当前行程")).getByText(board)).toBeTruthy();
    expect(screen.queryByText("监控异常")).toBeNull();
    expect(screen.queryByRole("button", { name: "查看运行详情" })).toBeNull();
    expect(screen.getByRole("region", { name: "下一步" }).textContent).toContain(
      environmentReady ? "请先打开登录页。" : "请先检查运行环境",
    );
    await userEvent.click(screen.getByRole("button", { name: label }));
    expect(railwatchStore.getState().activePage).toBe("系统设置");
    expect(railwatchStore.getState().pageSection).toBe(section);
  });

  test("runtime failures remain actionable even before the environment check", async () => {
    railwatchStore.setState({ status: {
      ...defaultStatus,
      phase: "error",
      risk_level: "critical",
      error_message: "运行时中断",
    } });
    render(<DashboardPage />);

    expect(screen.getByRole("heading", { name: "需要关注运行状态" })).toBeTruthy();
    expect(within(screen.getByLabelText("当前行程")).getByText("监控异常")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "查看运行详情" }));
    expect(railwatchStore.getState().activePage).toBe("购票监控");
    expect(railwatchStore.getState().pageSection).toBe("monitor-controls");
  });
  test("trip edit targets the trip controls without an automation shortcut when enabled", async () => {
    railwatchStore.setState({
      config: { ...defaultConfig, auto_submit: true, auto_alternate: true },
    });
    render(<DashboardPage />);
    expect(screen.queryByLabelText("自动化状态")).toBeNull();
    expect(screen.queryByText("自动化已开启")).toBeNull();
    expect(screen.queryByRole("button", { name: /配置自动化/ })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "编辑行程" }));
    expect(railwatchStore.getState().activePage).toBe("行程设置");
    expect(railwatchStore.getState().pageSection).toBe("trip-basics");
  });
  test("shows five workflow steps and keeps mutation controls on their pages", () => {
    render(<DashboardPage />);
    expect(
      within(screen.getByRole("list", { name: "监控流程" })).getAllByRole(
        "listitem",
      ),
    ).toHaveLength(5);
    expect(screen.queryByRole("switch")).toBeNull();
    expect(screen.queryByRole("button", { name: /启动监控/ })).toBeNull();
  });
  test("uses the task snapshot and never fabricates a next query deadline", () => {
    railwatchStore.setState({
      config: { ...defaultConfig, from_station_cn: "广州" },
      status: {
        ...defaultStatus,
        monitoring: true,
        current_config: { ...defaultConfig },
      },
      monitorLoops: 9,
    });
    render(<DashboardPage />);
    expect(screen.getByText("北京")).toBeTruthy();
    expect(screen.queryByText("广州")).toBeNull();
    expect(screen.getByText("北京 · 出发站")).toBeTruthy();
    expect(screen.queryByText("广州 · 出发站")).toBeNull();
    expect(screen.getByText("查询次数").parentElement?.textContent).toContain(
      "9",
    );
    expect(within(screen.getByRole("region", { name: "查询脉搏" })).getByRole("status").textContent).toBe("监控中");
    expect(screen.queryByText(/下次查询/)).toBeNull();
  });
  test("prioritizes pending payment over monitoring and environment flags", async () => {
    railwatchStore.setState({
      status: {
        ...defaultStatus,
        monitoring: true,
        order: { status: "pending_payment" },
      },
    });
    render(<DashboardPage />);
    expect(screen.getByRole("heading", { name: "预订待支付" })).toBeTruthy();
    await userEvent.click(
      screen.getByRole("button", { name: "查看并处理订单" }),
    );
    expect(railwatchStore.getState().activePage).toBe("购票监控");
    expect(railwatchStore.getState().pageSection).toBe("monitor-attention");
  });
  test("surfaces manual action before idle setup", () => {
    railwatchStore.setState({
      lastHumanAction: { title: "请完成核验", message: "打开官方页面继续" },
    });
    render(<DashboardPage />);
    expect(screen.getByRole("heading", { name: "请完成核验" })).toBeTruthy();
  });

  test("moves the workflow current step to hit after a ticket hit", () => {
    railwatchStore.setState({
      status: {
        ...defaultStatus,
        environment_ready: true,
        login_ready: true,
        query_ready: true,
        summary: "已命中目标车票",
      },
      hits: [
        {
          train_code: "G101",
          seat_type: "二等座",
          status: "有票",
          source: "query",
          detail: "G101 二等座有票",
          label: "G101 二等座有票",
        },
      ],
    });

    render(<DashboardPage />);

    const workflow = screen.getByRole("list", { name: "监控流程" });
    const currentSteps = workflow.querySelectorAll('[aria-current="step"]');

    expect(currentSteps).toHaveLength(1);
    expect(currentSteps[0].textContent).toContain("命中");
    expect(currentSteps[0].textContent).toContain("发现记录");
  });

  test("keeps hit as the only current step when a hit arrives before readiness flags", () => {
    railwatchStore.setState({
      hits: [
        {
          train_code: "G102",
          seat_type: "一等座",
          status: "有票",
          source: "query",
          detail: "G102 一等座有票",
          label: "G102 一等座有票",
        },
      ],
    });

    render(<DashboardPage />);

    const workflow = screen.getByRole("list", { name: "监控流程" });
    const currentSteps = workflow.querySelectorAll('[aria-current="step"]');
    const environmentStep = within(workflow)
      .getAllByRole("listitem")
      .find((step) => step.textContent?.includes("环境"));

    expect(currentSteps).toHaveLength(1);
    expect(currentSteps[0].textContent).toContain("命中");
    expect(environmentStep).toBeTruthy();
    expect(environmentStep?.getAttribute("aria-current")).toBeNull();
  });

  test("warns when the saved departure date has already passed", () => {
    railwatchStore.setState({
      config: { ...defaultConfig, date: "2020-01-01" },
    });

    render(<DashboardPage />);

    expect(screen.getAllByRole("status").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/出发日期已过去/).length).toBeGreaterThanOrEqual(
      1,
    );
  });

  test("readiness uses loaded seat capabilities like the monitor page", () => {
    railwatchStore.getState().setRehearsalEnabled(true);
    const seats = [{ name: "二等座", query: true, regular: true, alternate: true },
      { name: "一等座", query: true, regular: true, alternate: false }];
    for (const [seat, heading] of [["一等座", "完善你的行程"], ["二等座", "开售前先彩排一次"]]) {
      railwatchStore.setState({
        runtime: { ...defaultRuntimeInfo, state: { ...defaultStatus }, seat_capabilities: seats },
        status: { ...defaultStatus, environment_ready: true, login_ready: true, query_ready: true },
        config: { ...defaultConfig, date: isoDaysFromToday(3), auto_alternate: true, train_code: "G101",
          passengers: "测试甲", seat_keyword: seat },
      });
      render(<DashboardPage />);
      expect(screen.getByRole("heading", { name: heading })).toBeTruthy();
      cleanup();
    }
  });

  test("does not warn for a date inside the presale window", () => {
    railwatchStore.setState({
      config: { ...defaultConfig, date: isoDaysFromToday(3) },
    });

    render(<DashboardPage />);

    expect(screen.queryByText(/出发日期已过去/)).toBeNull();
    expect(screen.queryByText(/超出预售期/)).toBeNull();
  });

  test("disabled rehearsal never redirects the next action to its hidden panel", () => {
    railwatchStore.setState({
      status: { ...defaultStatus, environment_ready: true, login_ready: true, query_ready: true },
      config: { ...defaultConfig, date: isoDaysFromToday(3), timer_enabled: true,
        sale_at: `${isoDaysFromToday(1)}T10:00:00+08:00` },
    });
    render(<DashboardPage />);
    expect(screen.queryByRole("button", { name: "前往起售彩排" })).toBeNull();
    expect(screen.getByRole("button", { name: "进入购票监控" })).toBeTruthy();
    act(() => railwatchStore.getState().setRehearsalEnabled(true));
    expect(screen.getByRole("button", { name: "前往起售彩排" })).toBeTruthy();
    act(() => railwatchStore.getState().setRehearsalEnabled(false));
    expect(screen.queryByRole("button", { name: "前往起售彩排" })).toBeNull();
  });
});
