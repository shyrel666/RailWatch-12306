// @vitest-environment jsdom
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, test } from "vitest";
import { defaultConfig, defaultRuntimeInfo, defaultStatus, railwatchStore } from "../store/railwatchStore";
import { DashboardPage } from "./DashboardPage";

function resetStore() {
  railwatchStore.setState({
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
    eventPanelVisible: true,
  });
}

describe("DashboardPage", () => {
  beforeEach(resetStore);
  afterEach(cleanup);

  test("renders the screenshot-style dashboard chrome and hides raw risk codes", async () => {
    const user = userEvent.setup();

    render(<DashboardPage />);

    expect(screen.getByLabelText("当前行程")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "行程概览" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "查询分析" })).toBeTruthy();
    expect(screen.getByText("检查环境")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "监控未运行" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "危险自动化（已锁定）" })).toBeTruthy();
    expect(screen.getByText("低风险")).toBeTruthy();
    expect(screen.queryByText("notice")).toBeNull();

    await user.click(screen.getByRole("button", { name: "查看 / 编辑行程" }));

    expect(railwatchStore.getState().activePage).toBe("行程设置");
  });

  test("shows a five-step workflow and keeps setup fields off the dashboard", () => {
    render(<DashboardPage />);

    const workflow = screen.getByRole("list", { name: "监控流程" });
    const steps = within(workflow).getAllByRole("listitem");

    expect(steps).toHaveLength(5);
    expect(steps[0].textContent).toContain("环境");
    expect(steps[2].textContent).toContain("查询");
    expect(steps[4].textContent).toContain("命中");
    expect(screen.getByText("站点范围")).toBeTruthy();
    expect(screen.getByText("请求模式")).toBeTruthy();
    expect(screen.queryByText("并发请求")).toBeNull();
    expect(screen.queryByText("自动跳转支付")).toBeNull();
    expect(screen.queryByRole("button", { name: "了解更多风险说明" })).toBeNull();
    expect(screen.getByLabelText("自动化状态")).toBeTruthy();
    expect(screen.queryByLabelText("乘客")).toBeNull();
  });

  test("uses a single dashboard action to enter the monitor page", async () => {
    const user = userEvent.setup();

    render(<DashboardPage />);

    expect(screen.queryByRole("button", { name: /启动监控/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /停止监控/ })).toBeNull();

    await user.click(screen.getByRole("button", { name: /进入购票监控/ }));
    expect(railwatchStore.getState().activePage).toBe("购票监控");
  });

  test("shows the configured date range instead of a hardcoded range", () => {
    railwatchStore.setState({
      config: { ...defaultConfig, date: "2026-06-10", date_range: "±2天" },
    });

    render(<DashboardPage />);

    expect(screen.getByText("6月10日（±2天）")).toBeTruthy();
    expect(screen.queryByText("6月10日（±3天）")).toBeNull();
  });

  test("does not fabricate elapsed time or submission counts", () => {
    railwatchStore.setState({
      status: { ...defaultStatus, query_ready: true, monitoring: true },
      monitorLoops: 9,
    });

    render(<DashboardPage />);

    expect(screen.queryByText("00:12")).toBeNull();
    expect(screen.queryByText("成功提交")).toBeNull();
    expect(screen.getByText("请求次数").parentElement?.textContent).toContain("9");
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
});
