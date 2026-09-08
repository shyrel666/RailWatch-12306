import { useEffect, useState } from "react";
import { App as AntApp, Button } from "antd";
import { ArrowUpCircle, ExternalLink, Github } from "lucide-react";
import appIconUrl from "../../assets/images/icon.png";
import { formatAppVersion } from "../lib/formatSystemStatus";
import { railwatchApi } from "../lib/railwatchApi";
import { useAppUpdate } from "../lib/useAppUpdate";
import { useRailWatchStore } from "../store/useRailWatchStore";
import type { AppInfo } from "../types";
import { BrandWordmark } from "./BrandWordmark";

const REPO_URL = "https://github.com/shyrel666/RailWatch-12306";

const PROJECT_LINKS = [
  { label: "GitHub 仓库", url: REPO_URL },
  { label: "发布与下载", url: `${REPO_URL}/releases` },
  { label: "问题反馈", url: `${REPO_URL}/issues` },
  { label: "更新日志", url: `${REPO_URL}/blob/main/CHANGELOG.md` },
  { label: "MIT 许可证", url: `${REPO_URL}/blob/main/LICENSE` },
];

export function AboutPage() {
  const runtime = useRailWatchStore((state) => state.runtime);
  const { message } = AntApp.useApp();
  const [appInfo, setAppInfo] = useState<AppInfo | null>(null);
  const { statusLabel, hasDownloadedUpdate, isUpdating, handlePrimaryAction } = useAppUpdate(runtime.app_version);

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
    <div className="sw-workspace about-workspace">
      <div className="about-panel">
        <div className="about-identity">
          <img alt="" className="about-icon" src={appIconUrl} />
          <BrandWordmark className="about-wordmark" label={runtime.app_display_name || "RailWatch 12306"} />
          <p className="about-version">{formatAppVersion(runtime.app_version)}</p>
        </div>

        <p className="about-tagline">把行程准备、起售监控与订单跟踪，放在一个桌面工作台。</p>

        <div className="about-actions">
          <Button
            icon={<ArrowUpCircle size={16} />}
            loading={isUpdating}
            onClick={() => void handlePrimaryAction()}
            type="primary"
          >
            {hasDownloadedUpdate ? "立即重启安装" : "检查更新"}
          </Button>
          <Button icon={<Github size={16} />} onClick={() => void openLink(REPO_URL)}>
            GitHub 仓库
          </Button>
        </div>
        <p className="about-update-note" role="status">
          {statusLabel}
        </p>

        <nav aria-label="项目与文档" className="about-links">
          {PROJECT_LINKS.map((link) => (
            <button className="about-link" key={link.label} onClick={() => void openLink(link.url)} type="button">
              {link.label}
              <ExternalLink size={13} />
            </button>
          ))}
        </nav>

        <div className="about-footnote">
          <p>不是 12306 官方产品；登录核验和支付需在官方页面完成，配置与订单记录只保存在本机。</p>
          {environment ? <p className="about-env">{environment}</p> : null}
        </div>
      </div>
    </div>
  );
}
