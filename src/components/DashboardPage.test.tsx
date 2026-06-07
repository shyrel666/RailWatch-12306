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

  test("guides the user to check the environment first and hides raw risk codes", async () => {
    const user = userEvent.setup();

    render(<DashboardPage />);

    expect(screen.getByRole("heading", { name: "下一步" })).toBeTruthy();
    expect(screen.getByRole("button", { name: /检查环境/ })).toBeTruthy();
    expect(screen.getByText("低风险")).toBeTruthy();
    expect(screen.queryByText("notice")).toBeNull();

    await user.click(screen.getByRole("button", { name: /检查环境/ }));

    expect(railwatchStore.getState().activePage).toBe("设置");
  });

  test("shows the operational workflow and keeps setup fields off the dashboard", () => {
    render(<DashboardPage />);

    const workflow = screen.getByRole("list", { name: "监控流程" });
    const steps = within(workflow).getAllByRole("listitem");

    expect(steps).toHaveLength(6);
    expect(steps[0].textContent).toContain("环境检查");
    expect(steps[0].textContent).toContain("当前");
    expect(steps.some((step) => step.textContent?.includes("命中提醒"))).toBe(true);
    expect(steps[5].textContent).toContain("人工确认");
    expect(screen.getByLabelText("当前路线")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "就绪状态" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "监控结果" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "风险控制" })).toBeTruthy();
    expect(screen.queryByLabelText("乘客")).toBeNull();
  });
});
