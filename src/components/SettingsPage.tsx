import { Button } from "antd";
import {
  Activity,
  Cpu,
  Database,
  Download,
  Globe,
  LogIn,
  Monitor,
  Trash2,
  Wifi,
  XCircle,
} from "lucide-react";
import { useRailWatchStore } from "../store/useRailWatchStore";
import { formatDataDirFreeSpace } from "../lib/formatSystemStatus";
import type { CommandRunner } from "./componentTypes";
import { ThemeControl } from "./ThemeControl";

export function SettingsPage({
  busy,
  runCommand,
}: {
  busy: string | null;
  runCommand: CommandRunner;
}) {
  const runtime = useRailWatchStore((state) => state.runtime);
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
  return (
    <div className="settings-workspace">
      <section className="settings-section" id="settings-appearance">
        <div className="section-heading">
          <h2>外观</h2>
          <span className="subtle-label">个性化你的工作台</span>
        </div>
        <div className="setting-row">
          <div>
            <strong>界面主题</strong>
            <p>点击按钮，在明亮、深色和跟随系统之间切换。</p>
          </div>
          <ThemeControl />
        </div>
      </section>
      <section
        className="settings-section"
        id="settings-environment"
        tabIndex={-1}
      >
        <div className="section-heading">
          <h2>环境与登录</h2>
          <Button
            icon={<Activity size={15} />}
            loading={busy === "checkEnvironment"}
            onClick={() => void runCommand("checkEnvironment")}
          >
            检查环境
          </Button>
        </div>
        <div className="health-list">
          {health.map((item) => (
            <div className="health-row" key={item.label}>
              <item.icon size={16} />
              <strong>{item.label}</strong>
              <span className={item.ok ? "health-ok" : "health-warning"}>
                {item.detail}
              </span>
            </div>
          ))}
        </div>
        <div className="setting-row">
          <div>
            <strong>ChromeDriver</strong>
            <p className="path-text">{runtime.chromedriver_path || "未安装"}</p>
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
          </div>
          <div className="button-row">
            <Button
              icon={<LogIn size={15} />}
              loading={busy === "openLogin"}
              onClick={() => void runCommand("openLogin")}
            >
              打开登录
            </Button>
            <Button
              loading={busy === "checkLogin"}
              onClick={() => void runCommand("checkLogin")}
            >
              检查登录
            </Button>
          </div>
        </div>
      </section>
      <section className="settings-section">
        <div className="section-heading">
          <h2>本地数据</h2>
          <span className="subtle-label">只保存在这台电脑</span>
        </div>
        <div className="setting-row">
          <div>
            <strong>数据目录</strong>
            <p className="path-text">{runtime.data_dir || "正在加载…"}</p>
          </div>
          <span
            className={
              runtime.data_dir_writable ? "health-ok" : "health-warning"
            }
          >
            {runtime.data_dir_writable ? "可读写" : "不可写"}
          </span>
        </div>
        <div className="setting-row">
          <span>磁盘可用</span>
          <strong>{formatDataDirFreeSpace(runtime.data_dir_free_bytes)}</strong>
        </div>
      </section>
      <section className="settings-section maintenance">
        <div className="section-heading">
          <h2>维护操作</h2>
          <span className="subtle-label">按需使用</span>
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
        <div className="setting-row">
          <div>
            <strong>清除数据</strong>
            <p>删除本地缓存与配置文件，操作无法撤销。</p>
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
  );
}
