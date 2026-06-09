import {
  Activity,
  AlertTriangle,
  Cpu,
  Database,
  Download,
  Globe,
  HardDrive,
  LogIn,
  Monitor,
  Trash2,
  Wifi,
  XCircle,
  Zap,
} from "lucide-react";
import { useRailWatchStore } from "../store/useRailWatchStore";
import type { CommandRunner } from "./componentTypes";

function formatBytes(bytes: number) {
  if (bytes <= 0) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  let size = bytes;
  while (size >= 1024 && i < units.length - 1) {
    size /= 1024;
    i += 1;
  }
  return `${size.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function StatusDot({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className={`sw-health-dot ${ok ? "ok" : "err"}`} title={label}>
      <span className="sw-dot-ring" />
      <span className="sw-dot-core" />
    </span>
  );
}

export function SettingsPage({
  busy,
  runCommand,
}: {
  busy: string | null;
  runCommand: CommandRunner;
}) {
  const runtime = useRailWatchStore((state) => state.runtime);
  const status = useRailWatchStore((state) => state.status);

  const healthItems = [
    { icon: Globe, label: "网络连接", ok: runtime.network_ok, detail: runtime.network_label },
    { icon: Wifi, label: "铁路服务", ok: runtime.railway_ok, detail: runtime.railway_label },
    { icon: Cpu, label: "核心模块", ok: runtime.core_available, detail: runtime.core_available ? "已加载" : runtime.core_import_error || "不可用" },
    { icon: Monitor, label: "Selenium", ok: runtime.selenium_available, detail: runtime.selenium_available ? "可用" : "未安装" },
    { icon: Database, label: "Driver 管理", ok: runtime.chromedriver_manager_available, detail: runtime.chromedriver_manager_available ? "可用" : "不可用" },
  ];

  return (
    <div className="sw-workspace">
      <header className="sw-header">
        <div className="sw-header-icon">
          <Cpu size={22} />
        </div>
        <div className="sw-header-copy">
          <h2>系统设置</h2>
          <p>运行环境状态与启动步骤</p>
        </div>
        <span className={`sw-phase-badge ${status.monitoring ? "active" : "idle"}`}>
          {status.monitoring ? "运行中" : "待命"}
        </span>
      </header>

      <section className="sw-info-strip">
        <div className="sw-info-cell">
          <HardDrive size={14} />
          <em>应用版本</em>
          <strong>{runtime.app_version}</strong>
        </div>
        <div className="sw-info-cell">
          <Database size={14} />
          <em>数据目录</em>
          <strong title={runtime.data_dir}>{runtime.data_dir || "—"}</strong>
        </div>
        <div className="sw-info-cell">
          <Zap size={14} />
          <em>ChromeDriver</em>
          <strong title={runtime.chromedriver_path}>{runtime.chromedriver_path || "未安装"}</strong>
        </div>
        <div className="sw-info-cell">
          <Monitor size={14} />
          <em>Chrome 版本</em>
          <strong>{runtime.chrome_version}</strong>
        </div>
        <div className="sw-info-cell">
          <HardDrive size={14} />
          <em>磁盘可用</em>
          <strong>{formatBytes(runtime.data_dir_free_bytes)}</strong>
        </div>
      </section>

      <section className="sw-section">
        <div className="sw-section-head">
          <h3>
            <Activity size={15} />
            环境健康
          </h3>
        </div>
        <div className="sw-health-grid">
          {healthItems.map((item) => (
            <div className={`sw-health-card ${item.ok ? "ok" : "err"}`} key={item.label}>
              <div className="sw-health-top">
                <item.icon size={16} />
                <StatusDot ok={item.ok} label={item.ok ? "正常" : "异常"} />
              </div>
              <span className="sw-health-label">{item.label}</span>
              <span className="sw-health-detail">{item.detail}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="sw-section">
        <div className="sw-section-head">
          <h3>
            <Zap size={15} />
            启动步骤
          </h3>
        </div>
        <div className="sw-action-grid">
          <button
            className="sw-action-card"
            disabled={busy === "checkEnvironment"}
            onClick={() => void runCommand("checkEnvironment")}
            type="button"
          >
            <Activity size={18} />
            <span className="sw-action-label">检查环境</span>
            <span className="sw-action-desc">检测运行依赖与网络连通性</span>
          </button>
          <button
            className="sw-action-card primary"
            disabled={busy === "downloadChromeDriver"}
            onClick={() => void runCommand("downloadChromeDriver")}
            type="button"
          >
            <Download size={18} />
            <span className="sw-action-label">下载 ChromeDriver</span>
            <span className="sw-action-desc">自动匹配 Chrome 版本并安装</span>
          </button>
          <button
            className="sw-action-card"
            disabled={busy === "openLogin"}
            onClick={() => void runCommand("openLogin")}
            type="button"
          >
            <LogIn size={18} />
            <span className="sw-action-label">打开登录</span>
            <span className="sw-action-desc">启动浏览器并导航至 12306</span>
          </button>
          <button
            className="sw-action-card"
            disabled={busy === "checkLogin"}
            onClick={() => void runCommand("checkLogin")}
            type="button"
          >
            <LogIn size={18} />
            <span className="sw-action-label">检查登录</span>
            <span className="sw-action-desc">验证当前 12306 会话状态</span>
          </button>
        </div>
      </section>

      <section className="sw-section sw-danger-section">
        <div className="sw-section-head">
          <h3 className="sw-danger-title">
            <AlertTriangle size={15} />
            高风险操作
          </h3>
          <span className="sw-danger-warning">操作不可撤销</span>
        </div>
        <div className="sw-danger-grid">
          <button
            className="sw-danger-card"
            disabled={busy === "closeBrowser"}
            onClick={() => void runCommand("closeBrowser")}
            type="button"
          >
            <XCircle size={18} />
            <span className="sw-action-label">关闭浏览器</span>
            <span className="sw-action-desc">终止 Selenium 浏览器进程</span>
          </button>
          <button
            className="sw-danger-card"
            disabled={busy === "clearLocalData"}
            onClick={() => void runCommand("clearLocalData")}
            type="button"
          >
            <Trash2 size={18} />
            <span className="sw-action-label">清除数据</span>
            <span className="sw-action-desc">删除本地缓存与配置文件</span>
          </button>
        </div>
      </section>
    </div>
  );
}
