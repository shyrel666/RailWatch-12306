import { useEffect, useState } from "react";
import { App as AntApp, Button, ConfigProvider } from "antd";
import {
  ArrowUpCircle,
  ArrowUpRight,
  Github,
  HardDrive,
  History,
  MessageSquareWarning,
  Package,
  Scale,
  ShieldCheck,
  Train,
  type LucideIcon,
} from "lucide-react";
import appIconUrl from "../../assets/images/icon.png";
import { formatAppVersion } from "../lib/formatSystemStatus";
import { railwatchApi } from "../lib/railwatchApi";
import { getBoardTheme } from "../lib/theme";
import { useAppUpdate } from "../lib/useAppUpdate";
import { useRailWatchStore } from "../store/useRailWatchStore";
import type { AppInfo } from "../types";
import { BrandWordmark } from "./BrandWordmark";

const REPO_URL = "https://github.com/shyrel666/RailWatch-12306";

const PROJECT_LINKS: { label: string; detail: string; url: string; icon: LucideIcon }[] = [
  { label: "发布与下载", detail: "Windows 与 macOS 安装包", url: `${REPO_URL}/releases`, icon: Package },
  { label: "问题反馈", detail: "报告问题或提出建议", url: `${REPO_URL}/issues`, icon: MessageSquareWarning },
  { label: "更新日志", detail: "每个版本的变化", url: `${REPO_URL}/blob/main/CHANGELOG.md`, icon: History },
  { label: "MIT 许可证", detail: "开源许可条款", url: `${REPO_URL}/blob/main/LICENSE`, icon: Scale },
];

const NOTES: { icon: LucideIcon; title: string; text: string }[] = [
  { icon: Train, title: "非官方工具", text: "不是 12306 官方产品。" },
  { icon: ShieldCheck, title: "人工完成关键步骤", text: "登录核验和支付需在官方页面完成，发现余票不代表订单已创建。" },
  { icon: HardDrive, title: "数据留在本机", text: "配置与订单记录只保存在本机。" },
];

export function AboutPage() {
  const runtime = useRailWatchStore((state) => state.runtime);
  const { message } = AntApp.useApp();
  const [appInfo, setAppInfo] = useState<AppInfo | null>(null);
  const { statusLabel, hasDownloadedUpdate, hasManualDownload, isUpdating, handlePrimaryAction } = useAppUpdate(runtime.app_version);

  useEffect(() => {
    let cancelled = false;
    void railwatchApi
      .getAppInfo()
      .then((info) => {
        if (!cancelled) {
          setAppInfo(info);
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  const openLink = async (url: string) => {
    try {
      const result = await railwatchApi.openExternal(url);
      if (!result.ok) {
        message.error("无法打开链接，请在浏览器中手动访问。");
      }
    } catch {
      message.error("无法打开链接，请在浏览器中手动访问。");
    }
  };

  const environment = [
    appInfo ? `Electron ${appInfo.electronVersion}` : null,
    appInfo ? `Chromium ${appInfo.chromeVersion}` : null,
    appInfo ? `Node.js ${appInfo.nodeVersion}` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <div className="about-workspace">
      <ConfigProvider theme={getBoardTheme()}>
        <section className="departure-board about-board" aria-label="应用信息">
          <div className="board-main">
            <div className="about-identity">
              <img alt="" className="about-icon" src={appIconUrl} />
              <div>
                <BrandWordmark className="about-wordmark" label={runtime.app_display_name || "RailWatch 12306"} />
                <p className="about-tagline">把行程准备、起售监控与订单跟踪，放在一个桌面工作台。</p>
              </div>
            </div>
            <div className="board-display">
              <span>当前版本</span>
              <strong className="board-led">{formatAppVersion(runtime.app_version)}</strong>
              <small className="about-update-note" role="status">{statusLabel}</small>
            </div>
          </div>
          <div className="board-foot">
            <dl className="board-facts">
              <div>
                <dt>运行环境</dt>
                <dd className="about-env">{environment || "正在读取…"}</dd>
              </div>
            </dl>
            <div className="board-actions">
              <Button icon={<Github size={16} />} onClick={() => void openLink(REPO_URL)}>
                GitHub 仓库
              </Button>
              <Button
                icon={<ArrowUpCircle size={16} />}
                loading={isUpdating}
                onClick={() => void handlePrimaryAction()}
                type="primary"
              >
                {hasDownloadedUpdate ? "立即重启安装" : hasManualDownload ? "前往下载" : "检查更新"}
              </Button>
            </div>
          </div>
        </section>
      </ConfigProvider>

      <div className="about-grid">
        <nav aria-label="项目与文档" className="about-card about-links">
          <h2>项目与文档</h2>
          {PROJECT_LINKS.map((link) => (
            <button className="about-link" key={link.label} onClick={() => void openLink(link.url)} type="button">
              <span className="about-link-icon"><link.icon size={16} aria-hidden="true" /></span>
              <span className="about-link-copy">
                <strong>{link.label}</strong>
                <small>{link.detail}</small>
              </span>
              <ArrowUpRight size={15} aria-hidden="true" />
            </button>
          ))}
        </nav>
        <section className="about-card about-notes" aria-label="使用须知">
          <h2>使用须知</h2>
          <ul>
            {NOTES.map((note) => (
              <li key={note.title}>
                <span className="about-note-icon"><note.icon size={16} aria-hidden="true" /></span>
                <div>
                  <strong>{note.title}</strong>
                  <p>{note.text}</p>
                </div>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}
