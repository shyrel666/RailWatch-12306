import { Button, Table, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";
import { Activity, Bell, Database, LogIn, Radar, Search, ShieldAlert } from "lucide-react";
import { useRailWatchStore } from "../store/useRailWatchStore";
import type { RailWatchPage, RailWatchStatus, TicketHit } from "../types";
import { MetricCard, StatusBadge, WorkflowStepper } from "./DisplayPrimitives";
import type { Tone, WorkflowStep } from "./DisplayPrimitives";
import { SectionTitle } from "./FormPrimitives";

const riskLabel: Record<string, string> = {
  notice: "低风险",
  success: "低风险",
  active: "监控中",
  warning: "需注意",
  critical: "高风险",
};

function getWorkflowSteps(status: RailWatchStatus, hasHits: boolean): WorkflowStep[] {
  const hitDone = hasHits;
  const steps: WorkflowStep[] = [
    { label: "环境检查", description: status.environment_ready ? "ChromeDriver 可用" : "先确认本机依赖", icon: Database, state: status.environment_ready ? "done" : "current" },
    { label: "人工登录", description: status.login_ready ? "登录页已打开" : "打开 12306 登录页", icon: LogIn, state: !status.environment_ready ? "pending" : status.login_ready ? "done" : "current" },
    { label: "查询分析", description: status.query_ready ? "页面结果已解析" : "保存行程后分析", icon: Search, state: !status.login_ready ? "pending" : status.query_ready ? "done" : "current" },
    { label: "启动监控", description: status.monitoring ? "受控刷新中" : "等待启动", icon: Radar, state: !status.query_ready ? "pending" : status.monitoring || hitDone ? "done" : "current" },
    { label: "命中提醒", description: hitDone ? "已有目标票命中" : "等待目标席别", icon: Bell, state: hitDone ? "done" : "pending" },
    { label: "人工确认", description: "订单确认和支付仍人工完成", icon: ShieldAlert, state: hitDone ? "current" : "pending" },
  ];
  let currentIndex = -1;
  for (let index = steps.length - 1; index >= 0; index -= 1) {
    if (steps[index].state === "current") {
      currentIndex = index;
      break;
    }
  }

  return steps.map((step, index) => {
    if (step.state !== "current" || index === currentIndex) {
      return step;
    }

    return { ...step, state: "done" };
  });
}

function getNextAction(status: RailWatchStatus): { description: string; label: string; page: RailWatchPage } {
  if (!status.environment_ready) {
    return {
      description: "先确认 ChromeDriver、浏览器和本机依赖，再进入登录与查询流程。",
      label: "检查环境",
      page: "设置",
    };
  }

  if (!status.login_ready) {
    return {
      description: "环境已经可用，下一步打开登录页并完成人工登录。",
      label: "去行程设置",
      page: "行程设置",
    };
  }

  if (!status.query_ready) {
    return {
      description: "登录状态已准备好，补齐行程后进行查询分析。",
      label: "完善行程",
      page: "行程设置",
    };
  }

  return {
    description: status.monitoring ? "监控正在运行，可到监控页查看刷新与查询结果。" : "查询分析完成，可以进入监控页启动受控刷新。",
    label: status.monitoring ? "查看监控" : "去监控",
    page: "监控",
  };
}

export function DashboardPage() {
  const status = useRailWatchStore((state) => state.status);
  const config = useRailWatchStore((state) => state.config);
  const hits = useRailWatchStore((state) => state.hits);
  const setActivePage = useRailWatchStore((state) => state.setActivePage);
  const hasHits = hits.length > 0;
  const workflowSteps = getWorkflowSteps(status, hasHits);
  const nextAction = getNextAction(status);
  const riskTone: Tone =
    status.risk_level === "critical" ? "red" : status.risk_level === "warning" ? "amber" : status.risk_level === "active" ? "teal" : "green";
  const monitorTone: Tone = status.monitoring ? "teal" : status.query_ready ? "blue" : "slate";
  const monitorLabel = status.monitoring ? "监控中" : status.query_ready ? "可启动" : "待准备";
  const currentRoute = `${config.from_station_cn || "未设置"} → ${config.to_station_cn || "未设置"}`;
  const cards = [
    {
      title: "环境",
      body: status.environment_ready ? "ChromeDriver 已通过" : "等待环境检查",
      meta: status.environment_ready ? "可用" : "待检查",
      tone: status.environment_ready ? "green" : "blue",
      icon: Database,
    },
    {
      title: "查询",
      body: status.query_ready ? "页面结果已解析" : "等待登录和行程分析",
      meta: status.query_ready ? "已解析" : "未就绪",
      tone: status.query_ready ? "green" : "indigo",
      icon: Search,
    },
    {
      title: "命中",
      body: hasHits ? hits[hits.length - 1].label : "尚未命中目标车票",
      meta: `${hits.length} 条`,
      tone: hasHits ? "green" : "slate",
      icon: Bell,
    },
  ] satisfies Array<{ body: string; icon: typeof Database; meta: string; title: string; tone: Tone }>;
  const columns: ColumnsType<TicketHit & { key: string }> = [
    { title: "车次", dataIndex: "train_code" },
    { title: "席别", dataIndex: "seat_type" },
    {
      title: "来源",
      dataIndex: "source",
      render: (source: string) => <Tag color={source === "alternate" ? "gold" : "green"}>{source === "alternate" ? "候补" : "查询"}</Tag>,
    },
    { title: "状态", dataIndex: "status" },
  ];
  const hitRows = hits.map((hit, index) => ({ ...hit, key: `${hit.train_code}-${hit.seat_type}-${index}` }));

  return (
    <div className="dashboard-grid dispatch-dashboard">
      <section className="content-band dispatch-hero" aria-label="当前路线">
        <div>
          <SectionTitle
            eyebrow="Current Route"
            title={currentRoute}
            action={<StatusBadge tone={monitorTone}>{monitorLabel}</StatusBadge>}
          />
          <dl className="data-list">
            <dt>日期</dt>
            <dd>{config.date || "待设置"}</dd>
            <dt>车次</dt>
            <dd>{config.train_code || "全部车次"}</dd>
            <dt>席别</dt>
            <dd>{config.seat_keyword || config.seat_prefer || "无偏好"}</dd>
            <dt>刷新</dt>
            <dd>{config.interval} 秒</dd>
          </dl>
        </div>
      </section>

      <section className="content-band dispatch-flow">
        <SectionTitle eyebrow="Rail Dispatch" title="监控流程" />
        <WorkflowStepper steps={workflowSteps} />
      </section>

      <section className="content-band next-action">
        <SectionTitle title="下一步" />
        <p>{nextAction.description}</p>
        <Button type="primary" icon={<Activity size={16} />} onClick={() => setActivePage(nextAction.page)}>
          {nextAction.label}
        </Button>
      </section>

      <section className="content-band">
        <SectionTitle title="就绪状态" />
        <div className="metric-grid">
          {cards.map((card) => (
            <MetricCard key={card.title} {...card} />
          ))}
        </div>
      </section>

      <section className="content-band">
        <SectionTitle title="监控结果" />
        <Table columns={columns} dataSource={hitRows} locale={{ emptyText: "尚未命中目标车票" }} pagination={false} size="middle" />
      </section>

      <section className="content-band risk-panel">
        <SectionTitle title="风险控制" action={<StatusBadge tone={riskTone}>{riskLabel[status.risk_level] ?? "未知风险"}</StatusBadge>} />
        <p>
          当前仅提供提醒与人工确认辅助；订单提交、候补改签和支付仍需人工完成。
          {status.auto_submit_enabled || status.auto_alternate_enabled ? " 请回到设置页关闭危险自动化。" : " 自动提交和自动候补保持关闭。"}
        </p>
      </section>
    </div>
  );
}
