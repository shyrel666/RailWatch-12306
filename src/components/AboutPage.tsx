import { useEffect, useState, type CSSProperties } from "react";
import { App as AntApp, Button, ConfigProvider } from "antd";
import {
  ArrowUpRight,
  Download,
  Github,
  History,
  MessageSquareWarning,
  Scale,
  type LucideIcon,
} from "lucide-react";
import appIconUrl from "../../assets/images/icon.png";
import { formatAppVersion } from "../lib/formatSystemStatus";
import { railwatchApi } from "../lib/railwatchApi";
import { getBoardTheme } from "../lib/theme";
import { useAppUpdate } from "../lib/useAppUpdate";
import { getUpdateSignal } from "../lib/updateDisplay";
import { useRailWatchStore } from "../store/useRailWatchStore";
import type { AppInfo, UpdateRuntimeState } from "../types";
import { BrandWordmark } from "./BrandWordmark";
import { UpdateStatusControl } from "./UpdateStatusControl";

const REPO_URL = "https://github.com/shyrel666/RailWatch-12306";

const PROJECT_LINKS: { label: string; detail: string; url: string; icon: LucideIcon }[] = [
  { label: "发布与下载", detail: "Windows 与 macOS 安装包", url: `${REPO_URL}/releases`, icon: Download },
  { label: "问题反馈", detail: "报告问题或提出建议", url: `${REPO_URL}/issues`, icon: MessageSquareWarning },
  { label: "更新日志", detail: "每个版本的变化", url: `${REPO_URL}/blob/main/CHANGELOG.md`, icon: History },
  { label: "MIT 许可证", detail: "开源许可条款", url: `${REPO_URL}/blob/main/LICENSE`, icon: Scale },
];

const NOTES: { title: string; text: string }[] = [
  { title: "非官方工具", text: "不是 12306 官方产品，订单状态以官网为准。" },
  { title: "支付由你完成", text: "登录核验与支付始终在官方页面进行。" },
  { title: "数据留在本机", text: "配置与订单记录只保存在这台电脑。" },
];

const PLATFORM_NAMES: Record<string, string> = { win32: "Windows", darwin: "macOS", linux: "Linux" };

/** The stub's slim track mirrors the panel's route: amber while travelling, green on arrival. */
function UpdateTrack({ state }: { state: UpdateRuntimeState }) {
  const preparing = state.phase === "available" && state.installMode !== "manual";
  if (state.phase !== "downloading" && state.phase !== "downloaded" && !preparing) return null;
  const known = state.phase === "downloaded" || (state.phase === "downloading" && Number.isFinite(state.downloadPercent));
  const percent = state.phase === "downloaded" ? 100 : Math.min(100, Math.max(0, state.downloadPercent ?? 0));
  return (
    <span
      aria-hidden="true"
      className={"about-update-track" + (state.phase === "downloaded" ? " arrived" : known ? "" : " scanning")}
      style={{ "--update-progress": percent / 100 } as CSSProperties}
    >
      <i />
    </span>
  );
}

function environmentFields(info: AppInfo) {
  const system = [PLATFORM_NAMES[info.platform] ?? info.platform, info.arch].filter(Boolean).join(" ");
  return [
    { label: "Electron", value: info.electronVersion },
    { label: "Chromium", value: info.chromeVersion },
    { label: "Node.js", value: info.nodeVersion },
    { label: "系统", value: system },
  ].filter((field) => field.value);
}

export function AboutPage() {
  const runtime = useRailWatchStore((state) => state.runtime);
  const { message } = AntApp.useApp();
  const [appInfo, setAppInfo] = useState<AppInfo | "unavailable" | null>(null);
  const update = useAppUpdate(runtime.app_version);
  const { updateState, statusLabel } = update;
  const signal = getUpdateSignal(updateState, update.isInstalling);

  useEffect(() => {
    let cancelled = false;
    void railwatchApi
      .getAppInfo()
      .then((info) => {
        if (!cancelled) {
          setAppInfo(info);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setAppInfo("unavailable");
        }
      });
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

  return (
    <div className="about-page">
      <ConfigProvider theme={getBoardTheme()}>
        <section className="departure-board about-ticket" aria-label="应用信息">
          <div className="about-ticket-main">
            <div className="about-identity">
              <img alt="" className="about-icon" src={appIconUrl} />
              <div className="about-identity-copy">
                <BrandWordmark className="about-wordmark" label={runtime.app_display_name || "RailWatch 12306"} />
                <p className="about-tagline">本地运行的 12306 购票助手：起售监控、自动提交、自动候补与订单跟踪。</p>
              </div>
            </div>
            <div className="about-ticket-footer">
              {appInfo && appInfo !== "unavailable" ? (
                <dl className="about-fields" aria-label="运行环境">
                  {environmentFields(appInfo).map((field) => (
                    <div key={field.label}>
                      <dt>{field.label}</dt>
                      <dd>{field.value}</dd>
                    </div>
                  ))}
                </dl>
              ) : (
                <p className="about-fields-pending">{appInfo ? "运行环境暂不可用" : "正在读取运行环境…"}</p>
              )}
              <Button
                className="about-repo"
                icon={<Github size={16} aria-hidden="true" />}
                onClick={() => void openLink(REPO_URL)}
              >
                GitHub 仓库
              </Button>
            </div>
          </div>
          <div className="about-ticket-stub">
            <span className="about-stub-caption">当前版本</span>
            <strong className="board-led">{formatAppVersion(runtime.app_version)}</strong>
            <p className="about-update-note" role="status">
              <i className={"lamp " + signal.tone + (signal.live ? " live" : "")} aria-hidden="true" />
              {statusLabel}
            </p>
            <UpdateTrack state={updateState} />
            <UpdateStatusControl appVersion={runtime.app_version} variant="button" update={update} />
          </div>
        </section>
      </ConfigProvider>

      <nav aria-label="项目与文档" className="about-section">
        <h2 className="about-section-title">项目与文档</h2>
        <div className="about-links">
          {PROJECT_LINKS.map(({ label, detail, url, icon: Icon }) => (
            <button className="about-link" key={label} onClick={() => void openLink(url)} type="button">
              <span className="about-link-icon">
                <Icon size={18} aria-hidden="true" />
              </span>
              <span className="about-link-copy">
                <strong>{label}</strong>
                <small>{detail}</small>
              </span>
              {label === "发布与下载" ? <Download className="about-link-arrow" size={16} aria-hidden="true" /> : <ArrowUpRight className="about-link-arrow" size={16} aria-hidden="true" />}
            </button>
          ))}
        </div>
      </nav>

      <section aria-label="使用须知" className="about-section">
        <h2 className="about-section-title">使用须知</h2>
        <ol className="about-notes">
          {NOTES.map((note, index) => (
            <li key={note.title}>
              <span className="about-note-index" aria-hidden="true">
                {String(index + 1).padStart(2, "0")}
              </span>
              <strong>{note.title}</strong>
              <p>{note.text}</p>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
