import { Button, Switch } from "antd";
import { useContext, useEffect, useRef, useState, type RefObject } from "react";
import {
  Activity,
  Bell,
  Cpu,
  Database,
  Download,
  Globe,
  HardDrive,
  LogIn,
  Monitor,
  Palette,
  SlidersHorizontal,
  Trash2,
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

function useActiveSection(navRef: RefObject<HTMLElement | null>) {
  const [active, setActive] = useState(SECTIONS[0].id);
  // A clicked section stays selected during its smooth scroll, even when the page
  // bottoms out before its heading reaches the bar. Manual scrolling releases it.
  const pinned = useRef<string | null>(null);
  useEffect(() => {
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
  }, [navRef]);
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
}: {
  busy: string | null;
  runCommand: CommandRunner;
}) {
  const runtime = useRailWatchStore((state) => state.runtime);
  const loginReady = useRailWatchStore((state) => state.status.login_ready);
  const [checkingLogin, setCheckingLogin] = useState(false);
  const [loginResult, setLoginResult] = useState<{ ready: boolean; message: string } | null>(null);
  const autoRehearsal = useRailWatchStore(state => state.rehearsalEnabled);
  const setAutoRehearsal = useRailWatchStore(state => state.setRehearsalEnabled);
  const [rehearsalSaving, setRehearsalSaving] = useState(false);
  const [closeToTray, setCloseToTray] = useState(false);
  const [traySaving, setTraySaving] = useState(false);
  const [trayReady, setTrayReady] = useState(false);
  const [trayError, setTrayError] = useState("");
  const navRef = useRef<HTMLElement>(null);
  const [activeSection, selectSection] = useActiveSection(navRef);
  useEffect(() => {
    let alive = true;
    void railwatchApi.command<RailWatchPreferences>("loadPreferences").then((value) => {
      if (alive) { setCloseToTray(value.close_to_tray === true); setAutoRehearsal(value.auto_rehearsal === true); setTrayReady(true); }
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
        <section
          className="settings-section"
          id="settings-environment"
          tabIndex={-1}
        >
          <div className="section-heading">
            <div className="section-title-copy">
              <h2>环境与登录</h2>
              <p>启动监控前，确认浏览器、驱动与 12306 会话都可用。</p>
            </div>
            <Button
              icon={<Activity size={15} />}
              loading={busy === "checkEnvironment"}
              onClick={() => void runCommand("checkEnvironment")}
            >
              检查环境
            </Button>
          </div>
          <div className="health-grid">
            {health.map((item) => (
              <div className={"health-tile" + (item.ok ? " ok" : " warn")} key={item.label}>
                <div className="health-tile-head">
                  <item.icon size={16} aria-hidden="true" />
                  <i className={"lamp " + (item.ok ? "go" : "wait")} aria-hidden="true" />
                </div>
                <span>{item.label}</span>
                <strong className={item.ok ? "health-ok" : "health-warning"}>
                  {item.detail}
                </strong>
              </div>
            ))}
          </div>
          <div className="setting-row">
            <div>
              <strong>ChromeDriver</strong>
              <p className="path-text mono">{runtime.chromedriver_path || "未安装"}</p>
              <p>Chrome 版本 · {runtime.chrome_version}</p>
            </div>
            <Button
              icon={<Download size={15} />}
              loading={busy === "downloadChromeDriver"}
              onClick={() => void runCommand("downloadChromeDriver")}
            >
              下载 ChromeDriver
            </Button>
          </div>
          <div className="setting-row" id="settings-login" tabIndex={-1}>
            <div>
              <strong>12306 登录</strong>
              <p>在官方页面完成登录后，检查当前会话。</p>
              <p
                role="status"
                aria-live="polite"
                className={"login-state " + (loginOk === null ? "" : loginOk ? "health-ok" : "health-warning")}
              >
                {checkingLogin ? "正在检查12306登录状态…" : loginResult?.message || (loginReady ? "登录已验证" : "尚未检查当前登录状态")}
              </p>
            </div>
            <div className="button-row">
              <Button
                icon={<LogIn size={15} />}
                loading={busy === "openLogin"}
                disabled={checkingLogin}
                onClick={() => { setLoginResult(null); void runCommand("openLogin"); }}
              >
                打开登录
              </Button>
              <Button
                loading={checkingLogin || busy === "checkLogin"}
                onClick={() => void checkLogin()}
              >
                检查登录
              </Button>
            </div>
          </div>
        </section>
        <section className="settings-section" id="settings-appearance">
          <div className="section-heading">
            <div className="section-title-copy">
              <h2>外观</h2>
              <p>选择界面主题；顶部的主题按钮也可以随时切换。</p>
            </div>
          </div>
          <ThemePicker />
        </section>
        <section className="settings-section" id="settings-behavior">
          <div className="section-heading">
            <div className="section-title-copy">
              <h2>运行偏好</h2>
              <p>窗口关闭方式与定时任务的准备动作。</p>
            </div>
          </div>
          <div className="setting-row">
            <div>
              <strong>关闭到托盘</strong>
              <p>关闭主窗口后继续运行监控；双击托盘图标可重新打开，退出请使用托盘菜单。</p>
            </div>
            <Switch aria-label="关闭到托盘" checked={closeToTray} disabled={!trayReady || traySaving} loading={traySaving} onChange={(next) => void saveTrayPreference(next)} />
          </div>
          <div className="setting-row">
            <div>
              <strong>启用起售彩排</strong>
              <p>定时任务开始等待前，仅在距起售超过 15 分钟时自动彩排。</p>
            </div>
            <Switch aria-label="启用起售彩排" checked={autoRehearsal} disabled={!trayReady || rehearsalSaving} loading={rehearsalSaving}
              onChange={next => { setRehearsalSaving(true); void railwatchApi.command<RailWatchPreferences>("savePreferences", { auto_rehearsal: next })
                .then(saved => { if (saved.auto_rehearsal !== next) throw new Error("彩排偏好未保存"); setAutoRehearsal(saved.auto_rehearsal === true); setTrayError(""); })
                .catch(() => setTrayError("自动彩排偏好未保存，请重试。" )).finally(() => setRehearsalSaving(false)); }} />
          </div>
          {trayError && <p role="alert" className="settings-error">{trayError}</p>}
        </section>
        <NotificationSettingsPanel />
        <section className="settings-section" id="settings-data">
          <div className="section-heading">
            <div className="section-title-copy">
              <h2>本地数据</h2>
              <p>配置、登录信息与订单记录只保存在这台电脑。</p>
            </div>
          </div>
          <div className="data-grid">
            <div className="data-tile">
              <div className="data-tile-head">
                <span>数据目录</span>
                <span className={"status-badge " + (runtime.data_dir_writable ? "green" : "amber")}>
                  {runtime.data_dir_writable ? "可读写" : "不可写"}
                </span>
              </div>
              <p className="path-text mono">{runtime.data_dir || "正在加载…"}</p>
            </div>
            <div className="data-tile">
              <div className="data-tile-head">
                <span>磁盘可用</span>
              </div>
              <strong>{formatDataDirFreeSpace(runtime.data_dir_free_bytes)}</strong>
            </div>
          </div>
        </section>
        <section className="settings-section maintenance" id="settings-maintenance">
          <div className="section-heading">
            <div className="section-title-copy">
              <h2>维护操作</h2>
              <p>按需使用；清除数据不可撤销。</p>
            </div>
          </div>
          <div className="setting-row">
            <div>
              <strong>关闭浏览器</strong>
              <p>结束当前浏览器会话。</p>
            </div>
            <Button
              icon={<XCircle size={15} />}
              loading={busy === "closeBrowser"}
              onClick={() => void runCommand("closeBrowser")}
            >
              关闭浏览器
            </Button>
          </div>
          <div className="setting-row danger-zone">
            <div>
              <strong>清除数据</strong>
              <p>关闭受控浏览器，删除本地配置、登录信息和历史记录；不会取消官方订单。</p>
            </div>
            <Button
              danger
              icon={<Trash2 size={15} />}
              loading={busy === "clearLocalData"}
              onClick={() => void runCommand("clearLocalData")}
            >
              清除数据
            </Button>
          </div>
        </section>
      </div>
    </div>
  );
}
