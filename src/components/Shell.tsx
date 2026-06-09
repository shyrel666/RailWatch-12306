import { useEffect, useState, type ReactNode } from "react";
import { Button, Tooltip } from "antd";
import {
  Activity,
  CheckCircle2,
  Circle,
  Clock3,
  Eye,
  EyeOff,
  FileDown,
  Gauge,
  MonitorPlay,
  Moon,
  ScrollText,
  Settings,
  Sun,
  TrainFront,
  XCircle,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import appIconUrl from "../../assets/images/icon.png";
import { formatAppVersion, formatDataDirFreeSpace, formatRuntimePhaseDetail, formatRuntimePhaseLabel, formatStatusClock, getRuntimePhaseTone } from "../lib/formatSystemStatus";
import type { RailWatchPage, RailWatchStatus, RuntimeInfo } from "../types";
import { UpdateStatusControl } from "./UpdateStatusControl";

export const RAILWATCH_PAGES: { name: RailWatchPage; icon: LucideIcon }[] = [
  { name: "仪表盘", icon: Gauge },
  { name: "行程设置", icon: TrainFront },
  { name: "购票监控", icon: MonitorPlay },
  { name: "系统设置", icon: Settings },
];

export function SidebarNav({
  activePage,
  appName,
  appVersion,
  dataDir,
  dataDirWritable,
  dataDirFreeBytes,
  onPageChange,
}: {
  activePage: RailWatchPage;
  appName: string;
  appVersion: string;
  dataDir: string;
  dataDirWritable: boolean;
  dataDirFreeBytes: number;
  onPageChange: (page: RailWatchPage) => void;
}) {
  const [now, setNow] = useState(() => new Date());
  const clock = formatStatusClock(now);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark">
          <img alt="RailWatch 12306 logo" src={appIconUrl} />
        </div>
        <div>
          <strong>{appName}</strong>
          <span>{formatAppVersion(appVersion)}</span>
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
      <div className="sidebar-footer">
        <div className="sidebar-status">
          <div className="sidebar-status-title">
            <span>数据目录</span>
            <em className={dataDirWritable ? "" : "warning"}>
              <Circle size={8} fill="currentColor" />
              {dataDirWritable ? "正常" : "异常"}
            </em>
          </div>
          <strong>{dataDir || "正在加载..."}</strong>
          <div className="sidebar-space">
            <span>可用空间</span>
            <strong>{formatDataDirFreeSpace(dataDirFreeBytes)}</strong>
          </div>
        </div>
        <div className="runtime-card" aria-label="系统时钟">
          <div className="runtime-card-head">
            <span className="runtime-card-eyebrow">
              <Clock3 size={14} />
              北京时间
            </span>
            <span className="runtime-clock-date">{clock.date}</span>
          </div>
          <time className="runtime-clock-time" dateTime={now.toISOString()}>
            {clock.time}
          </time>
        </div>
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
  onExportLog,
  onThemeChange,
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
  onExportLog: () => void;
  onThemeChange: (darkMode: boolean) => void;
  onToggleEventPanel: () => void;
}) {
  const shellClassName = [
    "app-shell",
    darkMode ? "dark" : "",
    eventPanelVisible ? "" : "without-event-panel",
    activePage === "仪表盘" ? "dashboard-shell" : "",
  ]
    .filter(Boolean)
    .join(" ");
  const isDashboard = activePage === "仪表盘";
  const hideTopbar = isDashboard || activePage === "行程设置" || activePage === "购票监控" || activePage === "系统设置";
  const workspaceClassName = [
    "workspace",
    isDashboard ? "dashboard-workspace" : "",
    activePage === "行程设置" ? "trip-setup-workspace-shell" : "",
    activePage === "购票监控" ? "monitor-workspace-shell" : "",
    activePage === "系统设置" ? "settings-workspace-shell" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={shellClassName}>
      <SidebarNav
        activePage={activePage}
        appName={runtime.app_display_name}
        appVersion={runtime.app_version}
        dataDir={runtime.data_dir}
        dataDirWritable={runtime.data_dir_writable}
        dataDirFreeBytes={runtime.data_dir_free_bytes}
        onPageChange={onPageChange}
      />

      <main className={workspaceClassName}>
        {hideTopbar ? null : (
          <header className="topbar">
            <div>
              <h1>{activePage}</h1>
              <p>{status.summary}</p>
            </div>
            <div aria-label="顶部操作" className="topbar-actions" role="toolbar">
              <StatusPill status={status} />
              <ThemeToggle darkMode={darkMode} onThemeChange={onThemeChange} />
              <Button
                icon={eventPanelVisible ? <EyeOff size={16} /> : <Eye size={16} />}
                onClick={onToggleEventPanel}
              >
                {eventPanelVisible ? "隐藏事件" : "显示事件"}
              </Button>
            </div>
          </header>
        )}
        <section className="page-surface">{children}</section>
      </main>

      {eventPanel}
      <BottomStatusBar
        darkMode={darkMode}
        eventPanelVisible={eventPanelVisible}
        runtime={runtime}
        status={status}
        onExportLog={onExportLog}
        onThemeChange={onThemeChange}
        onToggleEventPanel={onToggleEventPanel}
      />
    </div>
  );
}

function ThemeToggle({ darkMode, onThemeChange }: { darkMode: boolean; onThemeChange: (darkMode: boolean) => void }) {
  return (
    <div aria-label="外观" className="theme-toggle" role="group">
      <Tooltip title="明亮主题">
        <button
          aria-label="明亮主题"
          aria-pressed={!darkMode}
          className={!darkMode ? "theme-option active" : "theme-option"}
          onClick={() => onThemeChange(false)}
          type="button"
        >
          <Sun size={16} />
        </button>
      </Tooltip>
      <Tooltip title="暗黑主题">
        <button
          aria-label="暗黑主题"
          aria-pressed={darkMode}
          className={darkMode ? "theme-option active" : "theme-option"}
          onClick={() => onThemeChange(true)}
          type="button"
        >
          <Moon size={16} />
        </button>
      </Tooltip>
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

function BottomStatusBar({
  darkMode,
  eventPanelVisible,
  runtime,
  status,
  onExportLog,
  onThemeChange,
  onToggleEventPanel,
}: {
  darkMode: boolean;
  eventPanelVisible: boolean;
  runtime: RuntimeInfo;
  status: RailWatchStatus;
  onExportLog: () => void;
  onThemeChange: (darkMode: boolean) => void;
  onToggleEventPanel: () => void;
}) {
  const phaseTone = getRuntimePhaseTone(status.phase);
  const phaseLabel = formatRuntimePhaseLabel(status.status_message, status.phase);
  const phaseDetail = formatRuntimePhaseDetail(status.status_message, status.phase);

  return (
    <footer className="bottom-statusbar" aria-label="系统状态">
      <div className="statusbar-group">
        <span className={`statusbar-chip${runtime.network_ok ? "" : " warning"}`}>
          网络 <strong>{runtime.network_label}</strong>
        </span>
        <span className={`statusbar-chip${runtime.railway_ok ? "" : " warning"}`}>
          12306 <strong>{runtime.railway_label}</strong>
        </span>
        <span className={`statusbar-chip phase-${phaseTone}`} title={phaseDetail ?? undefined}>
          运行 <strong>{phaseLabel}</strong>
        </span>
      </div>
      <div className="statusbar-group right">
        <UpdateStatusControl appVersion={runtime.app_version} />
        <Tooltip title={darkMode ? "切换到明亮主题" : "切换到暗黑主题"}>
          <button
            aria-label={darkMode ? "切换到明亮主题" : "切换到暗黑主题"}
            className="statusbar-icon-button"
            onClick={() => onThemeChange(!darkMode)}
            type="button"
          >
            {darkMode ? <Moon size={16} /> : <Sun size={16} />}
          </button>
        </Tooltip>
        <Tooltip title={eventPanelVisible ? "隐藏事件日志" : "显示事件日志"}>
          <button
            aria-label={eventPanelVisible ? "隐藏事件日志" : "显示事件日志"}
            aria-pressed={eventPanelVisible}
            className={eventPanelVisible ? "statusbar-icon-button active" : "statusbar-icon-button"}
            onClick={onToggleEventPanel}
            type="button"
          >
            <ScrollText size={16} />
          </button>
        </Tooltip>
        <Tooltip title="导出日志">
          <button aria-label="导出日志" className="statusbar-icon-button" onClick={onExportLog} type="button">
            <FileDown size={16} />
          </button>
        </Tooltip>
      </div>
    </footer>
  );
}
