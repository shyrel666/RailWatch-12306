// @vitest-environment jsdom
import { fireEvent, render, screen, within } from "@testing-library/react";
import { CircleDot, Gauge } from "lucide-react";
import { describe, expect, test, vi } from "vitest";
import { EmptyState, MetricCard, RiskToggle, StatusBadge, WorkflowStepper } from "./DisplayPrimitives";

describe("DisplayPrimitives", () => {
  test("renders badges, metric cards, empty states, and workflow steps", () => {
    render(
      <div>
        <StatusBadge tone="green">可用</StatusBadge>
        <MetricCard title="环境" body="ChromeDriver 已通过" meta="可用" tone="green" icon={Gauge} />
        <WorkflowStepper steps={[{ label: "环境检查", description: "先确认本机依赖", icon: CircleDot, state: "current" }]} />
        <EmptyState title="暂无命中" description="等待目标席别出现" />
      </div>,
    );

    expect(screen.getAllByText("可用")).toHaveLength(2);
    expect(screen.getByLabelText("环境: ChromeDriver 已通过")).toBeTruthy();
    const workflow = screen.getByRole("list", { name: "监控流程" });
    expect(within(workflow).getByText("环境检查")).toBeTruthy();
    expect(screen.getByText("暂无命中")).toBeTruthy();
  });

  test("renders risk toggles with switch interaction", () => {
    const onChange = vi.fn();

    render(<RiskToggle checked={false} title="自动提交关闭" description="发现车票后仍需确认" onChange={onChange} />);

    expect(screen.getByText("自动提交关闭")).toBeTruthy();
    const safetySwitch = screen.getByRole("switch", { name: /自动提交关闭.*发现车票后仍需确认/ });
    fireEvent.click(safetySwitch);
    expect(onChange).toHaveBeenCalled();
  });
});
