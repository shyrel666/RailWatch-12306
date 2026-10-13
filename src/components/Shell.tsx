import { useEffect, useRef, useState, type ReactNode } from "react";
import { Drawer, Tooltip } from "antd";
import {
  ChartGantt,
  Gauge,
  Info,
  MonitorPlay,
  PanelLeftClose,
  PanelLeftOpen,
  ScrollText,
  ReceiptText,
  Settings,
  TrainFront,
  type LucideIcon,
} from "lucide-react";
import appIconUrl from "../../assets/images/icon.png";
import {
  formatAppVersion,
  formatRuntimePhaseDetail,
  formatRuntimePhaseLabel,
  formatStatusClock,
  getRuntimePhaseTone,
} from "../lib/formatSystemStatus";
import { useClock } from "../lib/useClock";
import { useSidebarPreference } from "../lib/useSidebarPreference";
import { AppUpdateContext, useAppUpdate } from "../lib/useAppUpdate";
import { useRailWatchStore } from "../store/useRailWatchStore";
import type { RailWatchPage, RailWatchStatus, RuntimeInfo } from "../types";
import { BrandWordmark } from "./BrandWordmark";
import { ThemeControl } from "./ThemeControl";
import { UpdateStatusControl } from "./UpdateStatusControl";

export const RAILWATCH_PAGES: { name: RailWatchPage; icon: LucideIcon }[] = [
  { name: "仪表盘", icon: Gauge },
  { name: "行程设置", icon: TrainFront },
  { name: "购票监控", icon: MonitorPlay },
  { name: "订单中心", icon: ReceiptText },
  { name: "运行复盘", icon: ChartGantt },
  { name: "系统设置", icon: Settings },
  { name: "关于", icon: Info },
];

export function SidebarNav({
  activePage,
  appName,
  collapsed = false,
  footer,
  monitoring = false,
  signals,
  onToggle,
  onPageChange,
}: {
  activePage: RailWatchPage;
  appName: string;
  collapsed?: boolean;
  footer?: ReactNode;
  monitoring?: boolean;
  signals?: ReactNode;
  onToggle?: () => void;
  onPageChange: (page: RailWatchPage) => void;
}) {
  const items = (start: number, end: number) =>
    RAILWATCH_PAGES.slice(start, end).map(({ name, icon: Icon }) => (
      <Tooltip
        title={collapsed ? name : undefined}
        placement="right"
        key={name}
      >
        <button
          className={"nav-item" + (activePage === name ? " active" : "")}
          aria-label={name}
          aria-current={activePage === name ? "page" : undefined}
          onClick={() => onPageChange(name)}
          type="button"
        >
          <Icon size={18} />
          <span>{name}</span>
          {monitoring && name === "购票监控" ? (
            <i className="nav-live" aria-hidden="true" />
          ) : null}
        </button>
      </Tooltip>
    ));
  return (
    <aside className="sidebar">
      <div className="brand">
        <img alt={collapsed ? appName : ""} src={appIconUrl} />
        <BrandWordmark label={appName || "RailWatch 12306"} />
      </div>
      <nav className="nav" aria-label="工作空间">
        {items(0, 5)}
      </nav>
      <div className="sidebar-spacer" />
      {signals}
      <nav className="nav nav-bottom" aria-label="应用">
        {items(5, 7)}
      </nav>
      <div className="sidebar-foot">
        {footer}
        <Tooltip title={collapsed ? "展开侧栏" : undefined} placement="right">
          <button
            className="statusbar-icon-button sidebar-collapse"
            aria-label={collapsed ? "展开侧栏" : "折叠侧栏"}
            aria-expanded={!collapsed}
            onClick={onToggle}
            type="button"
          >
            {collapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
          </button>
        </Tooltip>
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
  onExportLog?: () => void;
  onToggleEventPanel: () => void;
}) {
  const { collapsed, toggle: toggleSidebar } = useSidebarPreference();
  const update = useAppUpdate(runtime.app_version);
  const logAlert = useUnseenLogAlert(eventPanelVisible);
  const pageSection = useRailWatchStore((state) => state.pageSection);
  const logTriggerRef = useRef<HTMLButtonElement>(null);
  const contentRef = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!pageSection) {
      if (contentRef.current) contentRef.current.scrollTop = 0;
      return;
    }
    const target = document.getElementById(pageSection);
    if (target) {
      if (target instanceof HTMLDetailsElement) target.open = true;
      const scroller =
        target.closest<HTMLElement>(".trip-setup-form-scroll") ??
        contentRef.current;
      if (scroller) {
        const stickyHeader =
          pageSection === "monitor-attention" || pageSection === "monitor-human"
            ? (document
                .getElementById("monitor-controls")
                ?.getBoundingClientRect().height ?? 0)
            : pageSection.startsWith("settings-")
              ? (document
                  .querySelector(".settings-nav")
                  ?.getBoundingClientRect().height ?? 0)
              : 0;
        scroller.scrollTop = Math.max(
          0,
          scroller.scrollTop +
            target.getBoundingClientRect().top -
            scroller.getBoundingClientRect().top -
            stickyHeader -
            12,
        );
      }
      target.tabIndex = -1;
      const focusTarget =
        target.querySelector<HTMLElement>("summary, button, input") ?? target;
      focusTarget.focus({ preventScroll: true });
    }
  }, [activePage, pageSection]);
  return (
    <AppUpdateContext.Provider value={update}>
    <div
      className={
        "app-shell" +
        (darkMode ? " dark" : "") +
        (collapsed ? " collapsed" : "")
      }
    >
      <SidebarNav
        activePage={activePage}
        appName={runtime.app_display_name}
        collapsed={collapsed}
        monitoring={status.monitoring}
        signals={<SystemSignals runtime={runtime} status={status} />}
        footer={
          <>
            <span className="sidebar-version">
              {formatAppVersion(runtime.app_version)}
            </span>
            <UpdateStatusControl appVersion={runtime.app_version} />
          </>
        }
        onToggle={toggleSidebar}
        onPageChange={onPageChange}
      />
      <main
        className={
          "workspace" +
          (activePage === "购票监控" ? " monitor-workspace-shell" : "")
        }
      >
        <header className="page-header">
          <div className="page-heading">
            <h1>{activePage}</h1>
          </div>
          <div className="header-actions" role="group" aria-label="时间与常用工具">
            <HeaderClock />
            <span className="header-divider" aria-hidden="true" />
            <ThemeControl />
            <button
              ref={logTriggerRef}
              className="header-log-toggle"
              aria-label={eventPanelVisible ? "隐藏事件日志" : "显示事件日志"}
              aria-describedby={logAlert ? "header-log-alert" : undefined}
              aria-expanded={eventPanelVisible}
              aria-haspopup="dialog"
              title={eventPanelVisible ? "隐藏事件日志" : "显示事件日志"}
              onClick={onToggleEventPanel}
              type="button"
            >
              <ScrollText size={16} aria-hidden="true" />
              <span className="header-log-label">事件日志</span>
              {logAlert ? (
                <i className={"header-log-alert " + logAlert} id="header-log-alert">
                  <span className="sr-only">{logAlert === "error" ? "有新的错误" : "有新的警告"}</span>
                </i>
              ) : null}
            </button>
          </div>
        </header>
        <section className="page-surface" ref={contentRef}>
          {children}
        </section>
      </main>
      <Drawer
        afterOpenChange={(open) => {
          if (!open) logTriggerRef.current?.focus();
        }}
        title="事件日志"
        size={440}
        open={eventPanelVisible}
        onClose={onToggleEventPanel}
        forceRender
        className="log-drawer"
        styles={{
          body: {
            padding: 0,
            display: "flex",
            flexDirection: "column",
            overflow: "hidden",
          },
        }}
      >
        {eventPanel}
      </Drawer>
    </div>
    </AppUpdateContext.Provider>
  );
}

// Warnings and errors that arrived while the drawer was closed; opening it marks them seen.
function useUnseenLogAlert(visible: boolean) {
  const logs = useRailWatchStore((state) => state.logs);
  const latest = logs.at(-1)?.id ?? 0;
  const [seen, setSeen] = useState(0);
  useEffect(() => {
    if (visible) setSeen(latest);
  }, [visible, latest]);
  if (visible) return null;
  let alert: "warn" | "error" | null = null;
  for (let index = logs.length - 1; index >= 0 && (logs[index].id ?? 0) > seen; index -= 1) {
    if (logs[index].level === "ERROR") return "error";
    if (logs[index].level === "WARN") alert = "warn";
  }
  return alert;
}

function HeaderClock() {
  const now = useClock();
  const clock = formatStatusClock(new Date(now));
  return (
    <time
      className="header-clock"
      aria-label="系统时钟"
      title={`北京时间 ${clock.date} ${clock.weekday}`}
      dateTime={new Date(now).toISOString()}
    >
      <span>
        北京时间 · {Number(clock.date.slice(5, 7))}月{Number(clock.day)}日 {clock.weekday}
      </span>
      <strong>{clock.time}</strong>
    </time>
  );
}

function SystemSignals({
  runtime,
  status,
}: {
  runtime: RuntimeInfo;
  status: RailWatchStatus;
}) {
  const phaseTone = getRuntimePhaseTone(status.phase);
  // Ready is a healthy state, so it shares the green of the other signals;
  // a running monitor adds the pulse.
  const runLamp =
    status.phase === "order"
      ? "wait"
      : phaseTone === "active"
        ? "go live"
        : phaseTone === "error"
          ? "stop"
          : "go";
  const phaseLabel = formatRuntimePhaseLabel(status.status_message, status.phase);
  const rows = [
    { name: "网络", label: runtime.network_label, lamp: runtime.network_ok ? "go" : "wait" },
    { name: "12306", label: runtime.railway_label, lamp: runtime.railway_ok ? "go" : "wait" },
    {
      name: "运行",
      label: phaseLabel,
      lamp: runLamp,
      detail: formatRuntimePhaseDetail(status.status_message, status.phase),
    },
  ];
  return (
    <section className="system-signals" aria-label="系统状态">
      {rows.map((row) => (
        <div
          className="signal-row"
          key={row.name}
          title={row.detail ?? `${row.name} ${row.label}`}
        >
          <i className={"lamp " + row.lamp} aria-hidden="true" />
          <span>{row.name}</span>
          <strong>{row.label}</strong>
        </div>
      ))}
    </section>
  );
}
