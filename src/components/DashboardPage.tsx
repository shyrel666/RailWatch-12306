import { Table, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";
import { Activity, Bell, Database, LogIn, Radar, Search, ShieldAlert } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useRailWatchStore } from "../store/useRailWatchStore";
import type { TicketHit } from "../types";
import { SectionTitle } from "./FormPrimitives";

export function DashboardPage() {
  const status = useRailWatchStore((state) => state.status);
  const hits = useRailWatchStore((state) => state.hits);
  const cards = [
    {
      title: "环境",
      body: status.environment_ready ? "ChromeDriver 已通过" : "等待环境检查",
      meta: status.environment_ready ? "可用" : "待检查",
      tone: "blue",
      icon: Database,
    },
    {
      title: "登录",
      body: status.login_ready ? "登录页已打开" : "尚未打开登录页",
      meta: status.login_ready ? "就绪" : "人工",
      tone: "green",
      icon: LogIn,
    },
    {
      title: "查询",
      body: status.query_ready ? "查询分析完成" : "待配置站点与日期",
      meta: status.query_ready ? "已解析" : "未就绪",
      tone: "indigo",
      icon: Search,
    },
    {
      title: "监控",
      body: status.monitoring ? "监控中" : "未运行",
      meta: status.monitoring ? "运行中" : "受控刷新",
      tone: "teal",
      icon: Radar,
    },
    {
      title: "命中",
      body: hits.length ? hits[hits.length - 1].label : "尚未命中目标车票",
      meta: `${hits.length} 条记录`,
      tone: "green",
      icon: Bell,
    },
    {
      title: "风险",
      body: status.auto_submit_enabled || status.auto_alternate_enabled ? "已启用危险自动化" : "未启用危险自动化",
      meta: status.risk_level,
      tone: status.auto_submit_enabled || status.auto_alternate_enabled ? "amber" : "slate",
      icon: ShieldAlert,
    },
  ];
  const columns: ColumnsType<TicketHit & { key: string }> = [
    { title: "车次", dataIndex: "train_code" },
    { title: "席别", dataIndex: "seat_type" },
    {
      title: "来源",
      dataIndex: "source",
      render: (source: string) => <Tag color={source === "alternate" ? "gold" : "green"}>{source}</Tag>,
    },
    { title: "状态", dataIndex: "status" },
  ];
  return (
    <div className="dashboard-grid">
      <div className="status-grid">
        {cards.map((card) => (
          <StatusCard key={card.title} {...card} />
        ))}
      </div>
      <section className="content-band">
        <SectionTitle title="最近命中" />
        <Table
          columns={columns}
          dataSource={hits.map((hit, index) => ({ ...hit, key: `${hit.train_code}-${index}` }))}
          locale={{ emptyText: "尚未命中目标车票" }}
          pagination={false}
          size="middle"
        />
      </section>
    </div>
  );
}

function StatusCard({
  title,
  body,
  meta,
  tone,
  icon: Icon,
}: {
  title: string;
  body: string;
  meta: string;
  tone: string;
  icon: LucideIcon;
}) {
  return (
    <article className={`status-card ${tone}`}>
      <div className="status-icon">
        <Icon size={22} />
      </div>
      <div>
        <div className="status-card-head">
          <strong>{title}</strong>
          <span>{meta}</span>
        </div>
        <p>{body}</p>
      </div>
    </article>
  );
}
