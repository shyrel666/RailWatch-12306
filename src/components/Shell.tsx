import type { ReactNode } from "react";
import { Button } from "antd";
import { Activity, CheckCircle2, Eye, EyeOff, Gauge, MonitorPlay, TrainFront, Settings, XCircle } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { RailWatchPage, RailWatchStatus, RuntimeInfo } from "../types";

export const RAILWATCH_PAGES: { name: RailWatchPage; icon: LucideIcon }[] = [
  { name: "仪表盘", icon: Gauge },
  { name: "行程设置", icon: TrainFront },
  { name: "监控", icon: MonitorPlay },
  { name: "设置", icon: Settings },
];

export function SidebarNav({
  activePage,
  appName,
  dataDir,
  phase,
  onPageChange,
}: {
  activePage: RailWatchPage;
  appName: string;
  dataDir: string;
  phase: string;
  onPageChange: (page: RailWatchPage) => void;
}) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark">RW</div>
        <div>
          <strong>{appName}</strong>
          <span>{phase}</span>
        </div>
      </div>
      <nav className="nav">
        {RAILWATCH_PAGES.map((page) => {
          const Icon = page.icon;
          return (
            <button
              className={activePage === page.name ? "nav-item active" : "nav-item"}
              key={page.name}
              onClick={() => onPageChange(page.name)}
              type="button"
            >
              <Icon size={18} />
              <span>{page.name}</span>
            </button>
          );
        })}
      </nav>
      <div className="sidebar-status">
        <span>数据目录</span>
        <strong>{dataDir || "未加载"}</strong>
      </div>
    </aside>
  );
}

export function ShellLayout({
  activePage,
  children,
  darkMode,
  eventPanel,
  eventPanelVisible,
  runtime,
  status,
  onPageChange,
  onToggleEventPanel,
}: {
  activePage: RailWatchPage;
  children: ReactNode;
  darkMode: boolean;
  eventPanel: ReactNode;
  eventPanelVisible: boolean;
  runtime: RuntimeInfo;
  status: RailWatchStatus;
  onPageChange: (page: RailWatchPage) => void;
  onToggleEventPanel: () => void;
}) {
  const shellClassName = [
    "app-shell",
    darkMode ? "dark" : "",
    eventPanelVisible ? "" : "without-event-panel",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={shellClassName}>
      <SidebarNav
        activePage={activePage}
        appName={runtime.app_display_name}
        dataDir={runtime.data_dir}
        phase={status.phase}
        onPageChange={onPageChange}
      />

      <main className="workspace">
        <header className="topbar">
          <div>
            <h1>{activePage}</h1>
            <p>{status.summary}</p>
          </div>
          <div className="topbar-actions">
            <StatusPill status={status} />
            <Button
              icon={eventPanelVisible ? <EyeOff size={16} /> : <Eye size={16} />}
              onClick={onToggleEventPanel}
            >
              {eventPanelVisible ? "隐藏事件" : "显示事件"}
            </Button>
          </div>
        </header>
        <section className="page-surface">{children}</section>
      </main>

      {eventPanel}
    </div>
  );
}

function StatusPill({ status }: { status: RailWatchStatus }) {
  const icon = status.error_message ? <XCircle size={15} /> : status.monitoring ? <Activity size={15} /> : <CheckCircle2 size={15} />;
  return (
    <span className={`status-pill ${status.risk_level}`}>
      {icon}
      {status.error_message || status.status_message}
    </span>
  );
}
