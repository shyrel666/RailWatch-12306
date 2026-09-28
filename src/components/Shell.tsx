import { useEffect, useRef, type ReactNode } from "react";
import { Drawer, Tooltip } from "antd";
import {
  Gauge,
  ChevronRight,
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
  { name: "系统设置", icon: Settings },
  { name: "关于", icon: Info },
];
const descriptions: Record<RailWatchPage, string> = {
  仪表盘: "行程与运行概况",
  行程设置: "路线、乘客与查询策略",
  购票监控: "余票查询与任务控制",
  订单中心: "订单记录与状态核对",
  系统设置: "环境、通知与应用偏好",
  关于: "版本与应用信息",
};

export function SidebarNav({
  activePage,
  appName,
  collapsed = false,
  onToggle,
  onPageChange,
}: {
  activePage: RailWatchPage;
  appName: string;
  collapsed?: boolean;
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
        </button>
      </Tooltip>
    ));
  return (
    <aside className="sidebar">
      <div className="brand">
        <img alt={collapsed ? appName : ""} src={appIconUrl} />
        <BrandWordmark label={appName || "RailWatch 12306"} />
      </div>
      <div className="nav-caption">工作空间</div>
      <nav className="nav" aria-label="工作空间">
        {items(0, 4)}
      </nav>
      <nav className="nav nav-bottom" aria-label="应用">
        {items(4, 6)}
      </nav>
      <button
        className="nav-item sidebar-collapse"
        aria-label={collapsed ? "展开侧栏" : "折叠侧栏"}
        aria-expanded={!collapsed}
        onClick={onToggle}
        type="button"
      >
        {collapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
        <span>折叠侧栏</span>
      </button>
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
            <span className="page-eyebrow">工作空间</span>
            <ChevronRight className="page-breadcrumb" size={13} aria-hidden="true" />
            <h1>{activePage}</h1>
            <p>{descriptions[activePage]}</p>
          </div>
          <div className="header-actions">
            <ThemeControl />
            <button
              ref={logTriggerRef}
              className="quiet-button"
              aria-label={eventPanelVisible ? "隐藏事件日志" : "显示事件日志"}
              aria-expanded={eventPanelVisible}
              onClick={onToggleEventPanel}
              type="button"
            >
              <ScrollText size={16} />
              事件日志
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
        size={400}
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
      <BottomStatusBar runtime={runtime} status={status} />
    </div>
  );
}

function BottomStatusBar({
  runtime,
  status,
}: {
  runtime: RuntimeInfo;
  status: RailWatchStatus;
}) {
  const now = useClock();
  const clock = formatStatusClock(new Date(now));
  return (
    <footer className="bottom-statusbar" aria-label="系统状态">
      <div className="statusbar-group">
        <span
          className={"statusbar-chip" + (runtime.network_ok ? "" : " warning")}
        >
          网络 <strong>{runtime.network_label}</strong>
        </span>
        <span
          className={"statusbar-chip" + (runtime.railway_ok ? "" : " warning")}
        >
          12306 <strong>{runtime.railway_label}</strong>
        </span>
        <span
          className={
            "statusbar-chip phase-" + getRuntimePhaseTone(status.phase)
          }
          title={
            formatRuntimePhaseDetail(status.status_message, status.phase) ??
            undefined
          }
        >
          运行{" "}
          <strong>
            {formatRuntimePhaseLabel(status.status_message, status.phase)}
          </strong>
        </span>
      </div>
      <div className="statusbar-group right">
        <time
          aria-label="系统时钟"
          title={clock.date}
          dateTime={new Date(now).toISOString()}
        >
          北京时间 {clock.time}
        </time>
        <span>{formatAppVersion(runtime.app_version)}</span>
        <UpdateStatusControl appVersion={runtime.app_version} />
      </div>
    </footer>
  );
}
