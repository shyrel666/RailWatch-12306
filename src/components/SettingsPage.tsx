import { Button, Switch } from "antd";
import { useContext, useEffect, useRef, useState, type RefObject } from "react";
import {
  Activity,
  Bell,
  CalendarClock,
  Check,
  Cpu,
  Database,
  Download,
  FolderOpen,
  Globe,
  HardDrive,
  KeyRound,
  LogIn,
  Monitor,
  MonitorX,
  Palette,
  PanelBottomClose,
  SlidersHorizontal,
  Trash2,
  UserRound,
  Wifi,
  Wrench,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import { useRailWatchStore } from "../store/useRailWatchStore";
import { formatDataDirFreeSpace } from "../lib/formatSystemStatus";
import { themeOptions } from "../lib/theme";
import type { CommandRunner } from "./componentTypes";
import { ThemeContext } from "./ThemeControl";
import type { RailWatchStatus } from "../types";
import type { RailWatchPreferences } from "../types";
import { railwatchApi } from "../lib/railwatchApi";
import { NotificationSettingsPanel } from "./NotificationSettingsPanel";
import { SettingRow, SettingsSection } from "./SettingsPrimitives";
import { IDLE_POLICY } from "../lib/idlePolicy";

const SECTIONS: { id: string; label: string; icon: LucideIcon }[] = [
  { id: "settings-environment", label: "环境与登录", icon: Activity },
  { id: "settings-appearance", label: "外观", icon: Palette },
  { id: "settings-behavior", label: "运行偏好", icon: SlidersHorizontal },
  { id: "settings-notifications", label: "通知", icon: Bell },
  { id: "settings-data", label: "本地数据", icon: HardDrive },
  { id: "settings-maintenance", label: "维护操作", icon: Wrench },
];

const themeDescriptions: Record<string, string> = {
  system: "随 Windows／macOS 切换",
  light: "暖纸色底，白天使用",
  dark: "夜间盯票更护眼",
};

function ThemePicker() {
  const { mode, disabled, onChange } = useContext(ThemeContext);
  return (
    <div className="theme-picker" role="radiogroup" aria-label="界面主题">
      {themeOptions.map((option) => (
        <button
          aria-checked={mode === option.value}
          className={"theme-option" + (mode === option.value ? " active" : "")}
          disabled={disabled}
          key={option.value}
          onClick={(event) => {
            const rect = event.currentTarget.getBoundingClientRect();
            onChange(option.value, {
              x: rect.left + rect.width / 2,
              y: rect.top + rect.height / 2,
            });
          }}
          role="radio"
          type="button"
        >
          <span className={"theme-preview " + option.value} aria-hidden="true">
            <i className="tp-side" />
            <i className="tp-board" />
            <i className="tp-card" />
            <i className="tp-card short" />
            <span className="theme-option-check"><Check size={11} strokeWidth={3} /></span>
          </span>
          <span className="theme-option-copy">
            <strong>{option.label}</strong>
            <small>{themeDescriptions[option.value]}</small>
          </span>
        </button>
      ))}
    </div>
  );
}

function useActiveSection(navRef: RefObject<HTMLElement | null>, suspended = false) {
  const [active, setActive] = useState(SECTIONS[0].id);
  // A clicked section stays selected during its smooth scroll, even when the page
  // bottoms out before its heading reaches the bar. Manual scrolling releases it.
  const pinned = useRef<string | null>(null);
  useEffect(() => {
    if (suspended) return undefined;
    const scroller = navRef.current?.closest<HTMLElement>(".page-surface");
    if (!scroller) return undefined;
    const update = () => {
      const bounds = scroller.getBoundingClientRect();
      const top = bounds.top + (navRef.current?.offsetHeight ?? 0);
      if (pinned.current) return;
      let current = SECTIONS[0].id;
      for (const section of SECTIONS) {
        const element = document.getElementById(section.id);
        if (element && element.getBoundingClientRect().top - top <= 48) current = section.id;
      }
      if (scroller.scrollTop + scroller.clientHeight >= scroller.scrollHeight - 4)
        current = SECTIONS[SECTIONS.length - 1].id;
      setActive(current);
    };
    const release = () => { pinned.current = null; };
    update();
    scroller.addEventListener("scroll", update, { passive: true });
    scroller.addEventListener("wheel", release, { passive: true });
    scroller.addEventListener("keydown", release);
    scroller.addEventListener("pointerdown", release);
    return () => {
      scroller.removeEventListener("scroll", update);
      scroller.removeEventListener("wheel", release);
      scroller.removeEventListener("keydown", release);
      scroller.removeEventListener("pointerdown", release);
    };
  }, [navRef, suspended]);
  const select = (id: string) => {
    pinned.current = id;
    setActive(id);
    document.getElementById(id)?.scrollIntoView?.({ behavior: "smooth", block: "start" });
  };
  return [active, select] as const;
}

export function SettingsPage({
  busy,
  runCommand,
  autoCheckEnvironment = false,
  onEnvironmentCheckStart,
}: {
  busy: string | null;
  runCommand: CommandRunner;
  autoCheckEnvironment?: boolean;
  onEnvironmentCheckStart?: () => void;
}) {
  const runtime = useRailWatchStore((state) => state.runtime);
  const environmentReady = useRailWatchStore((state) => state.status.environment_ready);
  const loginReady = useRailWatchStore((state) => state.status.login_ready);
  const [checkingLogin, setCheckingLogin] = useState(false);
  const [loginResult, setLoginResult] = useState<{ ready: boolean; message: string } | null>(null);
  const autoRehearsal = useRailWatchStore(state => state.rehearsalEnabled);
  const setAutoRehearsal = useRailWatchStore(state => state.setRehearsalEnabled);
  const [rehearsalSaving, setRehearsalSaving] = useState(false);
  const [closeToTray, setCloseToTray] = useState(false);
  const [idleKeepAlive, setIdleKeepAlive] = useState(false);
  const [idleSaving, setIdleSaving] = useState(false);
  const [traySaving, setTraySaving] = useState(false);
  const [trayReady, setTrayReady] = useState(false);
  const [trayError, setTrayError] = useState("");
  const navRef = useRef<HTMLElement>(null);
  const [activeSection, selectSection] = useActiveSection(navRef, autoCheckEnvironment);
  const checkingEnvironment = busy === "checkEnvironment";
  useEffect(() => {
    if (!autoCheckEnvironment) return;
    const timer = window.setTimeout(() => {
      onEnvironmentCheckStart?.();
      void runCommand("checkEnvironment");
    }, 1500);
    return () => window.clearTimeout(timer);
  }, [autoCheckEnvironment, onEnvironmentCheckStart, runCommand]);
  useEffect(() => {
    let alive = true;
    void railwatchApi.command<RailWatchPreferences>("loadPreferences").then((value) => {
      if (alive) { setCloseToTray(value.close_to_tray === true); setAutoRehearsal(value.auto_rehearsal === true);
        setIdleKeepAlive(value.idle_keep_alive === true); setTrayReady(true); }
    }).catch((error) => { if (alive) setTrayError(error instanceof Error ? error.message : "无法加载关闭偏好。"); });
    return () => { alive = false; };
  }, [setAutoRehearsal]);
  const saveTrayPreference = async (next: boolean) => {
    setTraySaving(true);
    setTrayError("");
    try {
      const saved = await railwatchApi.command<RailWatchPreferences>("savePreferences", { close_to_tray: next });
      if (saved.close_to_tray !== next) throw new Error("关闭偏好未保存，请重试。");
      setCloseToTray(next);
    } catch (error) {
      setTrayError(error instanceof Error ? error.message : "关闭偏好保存失败。");
    } finally { setTraySaving(false); }
  };
  const checkLogin = async () => {
    setCheckingLogin(true);
    setLoginResult(null);
    try {
      const result = await runCommand<RailWatchStatus>("checkLogin");
      setLoginResult({
        ready: result?.login_ready === true,
        message: result?.status_message || "检查未完成，请查看错误提示后重试。",
      });
    } catch (error) {
      setLoginResult({ ready: false, message: error instanceof Error ? error.message : "登录检查失败，请重试。" });
    } finally {
      setCheckingLogin(false);
    }
  };
  const health = [
    {
      icon: Globe,
      label: "网络连接",
      ok: runtime.network_ok,
      detail: runtime.network_label,
    },
    {
      icon: Wifi,
      label: "铁路服务",
      ok: runtime.railway_ok,
      detail: runtime.railway_label,
    },
    {
      icon: Cpu,
      label: "核心模块",
      ok: runtime.core_available,
      detail: runtime.core_available
        ? "已加载"
        : runtime.core_import_error || "不可用",
    },
    {
      icon: Monitor,
      label: "Selenium",
      ok: runtime.selenium_available,
      detail: runtime.selenium_available ? "可用" : "未安装",
    },
    {
      icon: Database,
      label: "Driver 管理",
      ok: runtime.chromedriver_manager_available,
      detail: runtime.chromedriver_manager_available ? "可用" : "不可用",
    },
  ];
  const loginOk = checkingLogin ? null : (loginResult?.ready ?? loginReady);
  if (autoCheckEnvironment) {
    return (
      <div className="settings-page-loading" role="status" aria-label="环境检查进度" aria-live="polite">
        <div className="settings-page-loading-content">
          <span className="settings-page-loading-rail" aria-hidden="true">
            <span className="settings-page-loading-track" />
            <i className="settings-page-loading-station start" />
            <i className="settings-page-loading-station middle" />
            <i className="settings-page-loading-station end" />
            <svg className="settings-page-loading-train" viewBox="-20 0 88 34" fill="none">
              <g className="settings-page-loading-speed" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                <path d="M-14 13h9M-19 19h13" />
              </g>
              <g stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round">
                <path className="loading-train-body" d="M5 9h33c10 0 18 6 26 17H5a3 3 0 0 1-3-3V12a3 3 0 0 1 3-3Z" />
                <path d="M3 22h57M11 6h21" strokeLinecap="round" />
              </g>
              <g fill="currentColor">
                <rect x="9" y="13" width="6" height="5" rx="1.2" />
                <rect x="19" y="13" width="6" height="5" rx="1.2" />
                <rect x="29" y="13" width="6" height="5" rx="1.2" />
                <path d="M42 13c4 1 8 4 12 8H42Z" />
                <circle cx="13" cy="28" r="2.5" />
                <circle cx="43" cy="28" r="2.5" />
              </g>
            </svg>
          </span>
          <strong>检查程序启动中</strong>
        </div>
      </div>
    );
  }
  return (
    <div className="settings-workspace">
      <nav className="settings-nav" aria-label="设置分组" ref={navRef}>
        {SECTIONS.map((section) => (
          <button
            aria-current={activeSection === section.id ? "true" : undefined}
            className={activeSection === section.id ? "active" : undefined}
            key={section.id}
            onClick={() => selectSection(section.id)}
            type="button"
          >
            <section.icon size={15} aria-hidden="true" />
            {section.label}
          </button>
        ))}
      </nav>
      <div className="settings-sections">
        <SettingsSection
          id="settings-environment"
          icon={Activity}
          title="环境与登录"
          description="开始监控前，确认浏览器、驱动与登录状态。"
          focusable
          actions={
            <Button
              className="settings-environment-check"
              type="primary"
              icon={<Activity size={15} />}
              disabled={checkingEnvironment}
              loading={checkingEnvironment}
              onClick={() => void runCommand("checkEnvironment")}
            >
              检查环境
            </Button>
          }
        >
          <div className="health-grid">
            {health.map((item) => (
              <div className={"health-tile" + (item.ok ? " ok" : " warn")} key={item.label}>
                <span className="health-tile-label">
                  <item.icon size={14} aria-hidden="true" />
                  {item.label}
                </span>
                <strong>
                  <i className={"lamp " + (item.ok ? "go" : "wait")} aria-hidden="true" />
                  <span>{item.detail}</span>
                </strong>
              </div>
            ))}
          </div>
          <SettingRow
            icon={Download}
            title="ChromeDriver"
            control={
              <Button
                icon={<Download size={15} />}
                disabled={checkingEnvironment}
                loading={busy === "downloadChromeDriver"}
                onClick={() => void runCommand("downloadChromeDriver")}
              >
                下载 ChromeDriver
              </Button>
            }
          >
            <p className="path-text mono">{runtime.chromedriver_path || "未安装"}</p>
            <p className="setting-meta">Chrome 版本 · {runtime.chrome_version}</p>
          </SettingRow>
          <SettingRow
            id="settings-login"
            icon={UserRound}
            title="12306 登录"
            control={
              <div className="button-row">
                <Button
                  icon={<LogIn size={15} />}
                  loading={busy === "openLogin"}
                  disabled={!environmentReady || checkingEnvironment || checkingLogin}
                  onClick={() => { setLoginResult(null); void runCommand("openLogin"); }}
                >
                  打开登录
                </Button>
                <Button
                  loading={checkingLogin || busy === "checkLogin"}
                  disabled={!environmentReady || checkingEnvironment || busy === "openLogin"}
                  onClick={() => void checkLogin()}
                >
                  检查登录
                </Button>
              </div>
            }
          >
            <p
              role="status"
              aria-live="polite"
              className={"login-state " + (loginOk === null ? "" : loginOk ? "health-ok" : "health-warning")}
            >
              {checkingEnvironment
                ? "正在检查运行环境，首次使用可能需要下载 Chrome 或驱动，请稍候…"
                : checkingLogin
                  ? "正在检查12306登录状态…"
                  : !environmentReady
                    ? "请先检查运行环境，再打开登录。"
                    : loginResult?.message || (loginReady ? "登录已验证" : "尚未检查当前登录状态")}
            </p>
          </SettingRow>
        </SettingsSection>
        <SettingsSection id="settings-appearance" icon={Palette} title="外观" description="选择界面配色，切换后立即生效。">
          <ThemePicker />
        </SettingsSection>
        <SettingsSection id="settings-behavior" icon={SlidersHorizontal} title="运行偏好" description="窗口关闭方式、开售前检查与登录保持。">
          <SettingRow
            icon={PanelBottomClose}
            title="关闭到托盘"
            control={<Switch aria-label="关闭到托盘" checked={closeToTray} disabled={!trayReady || traySaving} loading={traySaving} onChange={(next) => void saveTrayPreference(next)} />}
          >
            <p>关闭窗口后继续监控，从托盘图标重新打开或退出。</p>
          </SettingRow>
          <SettingRow
            icon={CalendarClock}
            title="启用起售彩排"
            control={
              <Switch aria-label="启用起售彩排" checked={autoRehearsal} disabled={!trayReady || rehearsalSaving} loading={rehearsalSaving}
                onChange={next => { setRehearsalSaving(true); void railwatchApi.command<RailWatchPreferences>("savePreferences", { auto_rehearsal: next })
                  .then(saved => { if (saved.auto_rehearsal !== next) throw new Error("彩排偏好未保存"); setAutoRehearsal(saved.auto_rehearsal === true); setTrayError(""); })
                  .catch(() => setTrayError("自动彩排偏好未保存，请重试。" )).finally(() => setRehearsalSaving(false)); }} />
            }
          >
            <p>在购票监控页提供开售前的只读检查；定时任务距起售超过 15 分钟时自动运行一次。</p>
          </SettingRow>
          <SettingRow
            icon={KeyRound}
            title="空闲时保持登录"
            control={
              <Switch aria-label="空闲时保持登录" checked={idleKeepAlive} disabled={!trayReady || idleSaving} loading={idleSaving}
                onChange={next => { setIdleSaving(true); void railwatchApi.command<RailWatchPreferences>("savePreferences", { idle_keep_alive: next })
                  .then(saved => { if (saved.idle_keep_alive !== next) throw new Error("保持登录偏好未保存"); setIdleKeepAlive(next); setTrayError(""); })
                  .catch(() => setTrayError("空闲保持登录偏好未保存，请重试。")).finally(() => setIdleSaving(false)); }} />
            }
          >
            <p>未在监控时，受控浏览器开着就每 {Math.round(IDLE_POLICY.login_keep_alive_seconds / 60)} 分钟检查一次登录状态，只检查登录、不查余票；已确认的登录失效时按通知设置提醒。</p>
          </SettingRow>
          {trayError && <p role="alert" className="settings-error">{trayError}</p>}
        </SettingsSection>
        <NotificationSettingsPanel />
        <SettingsSection id="settings-data" icon={HardDrive} title="本地数据" description="所有配置与记录只保存在这台电脑。">
          <div className="data-grid">
            <div className="data-tile">
              <div className="data-tile-head">
                <span><FolderOpen size={14} aria-hidden="true" />数据目录</span>
                <span className={"status-badge " + (runtime.data_dir_writable ? "green" : "amber")}>
                  {runtime.data_dir_writable ? "可读写" : "不可写"}
                </span>
              </div>
              <p className="path-text mono">{runtime.data_dir || "正在加载…"}</p>
            </div>
            <div className="data-tile">
              <div className="data-tile-head">
                <span><Database size={14} aria-hidden="true" />磁盘可用</span>
              </div>
              <strong>{formatDataDirFreeSpace(runtime.data_dir_free_bytes)}</strong>
            </div>
          </div>
        </SettingsSection>
        <SettingsSection id="settings-maintenance" className="maintenance" icon={Wrench} title="维护操作" description="结束浏览器会话，或清理这台电脑上的数据。">
          <SettingRow
            icon={MonitorX}
            title="关闭浏览器"
            control={
              <Button
                icon={<XCircle size={15} />}
                loading={busy === "closeBrowser"}
                onClick={() => void runCommand("closeBrowser")}
              >
                关闭浏览器
              </Button>
            }
          >
            <p>结束受控浏览器会话。</p>
          </SettingRow>
          <SettingRow
            icon={Trash2}
            title="清除数据"
            tone="danger"
            control={
              <Button
                danger
                icon={<Trash2 size={15} />}
                loading={busy === "clearLocalData"}
                onClick={() => void runCommand("clearLocalData")}
              >
                清除数据
              </Button>
            }
          >
            <p>删除本地配置、登录信息与历史记录，不可撤销；不会取消官方订单。</p>
          </SettingRow>
        </SettingsSection>
      </div>
    </div>
  );
}
