import { Button, Modal } from "antd";
import { Check, CircleAlert, Clock3, Info, LoaderCircle, Server } from "lucide-react";
import { useEffect, useState } from "react";
import type { EnvironmentProgress } from "../types";
import "../styles/environmentProgress.css";

const stageLabels: Record<EnvironmentProgress["stage"], string> = {
  checking: "正在检查本机环境",
  resolving: "正在匹配驱动版本",
  connecting: "正在连接下载源",
  downloading: "正在下载驱动",
  extracting: "正在解压驱动",
  installing: "正在安装驱动",
  retrying: "正在切换下载源",
  verifying: "正在验证浏览器",
  complete: "正在完成准备",
  error: "检查未完成",
};

function duration(seconds: number): string {
  const value = Math.max(0, Math.floor(seconds));
  if (value < 60) return `${value} 秒`;
  return `${Math.floor(value / 60)} 分 ${value % 60} 秒`;
}

function bytes(value: number): string {
  if (value >= 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(1)} MB`;
  if (value >= 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${Math.floor(value)} B`;
}

function nonNegative(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

export function EnvironmentProgressDialog({ progress, open, onClose }: {
  progress: EnvironmentProgress | null;
  open: boolean;
  onClose: () => void;
}) {
  const [now, setNow] = useState(() => Date.now() / 1000);
  const running = progress?.status === "running";
  useEffect(() => {
    if (!open || !running) return undefined;
    setNow(Date.now() / 1000);
    const timer = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => window.clearInterval(timer);
  }, [open, running]);

  if (!progress) return null;

  const elapsed = Math.max(0, (running ? Math.max(now, progress.updated_at) : progress.updated_at) - progress.started_at);
  const downloading = running && progress.stage === "downloading";
  const readingVersions = running && progress.stage === "resolving" && nonNegative(progress.downloaded_bytes);
  const transferring = downloading || readingVersions;
  const transferVerb = readingVersions ? "读取" : "下载";
  const stale = transferring && now - progress.updated_at >= 15;
  const downloaded = nonNegative(progress.downloaded_bytes) ? progress.downloaded_bytes : 0;
  const total = nonNegative(progress.total_bytes) && progress.total_bytes > 0 ? progress.total_bytes : null;
  const percent = total === null ? null : Math.min(100, Math.floor(downloaded / total * 100));
  const speed = !stale && nonNegative(progress.bytes_per_second) && progress.bytes_per_second > 0
    ? progress.bytes_per_second : null;
  const eta = speed !== null && total !== null && nonNegative(progress.eta_seconds) ? progress.eta_seconds : null;
  const checking = progress.operation === "checkEnvironment";
  const success = progress.status === "success";
  const title = checking ? "环境检查" : "下载 ChromeDriver";
  const heading = running ? (readingVersions ? "正在读取版本信息" : stageLabels[progress.stage])
    : success ? (checking ? "环境已就绪" : "驱动已安装") : (checking ? "环境检查未完成" : "驱动下载未完成");
  const descriptions: Record<EnvironmentProgress["stage"], string> = {
    checking: "核对运行组件、Chrome 与驱动版本。",
    resolving: "查找与本机 Chrome 匹配的驱动。",
    connecting: "连接成功后将自动开始下载。",
    downloading: checking ? "下载完成后，将自动安装并验证浏览器。" : "下载完成后，将自动解压并安装。",
    extracting: "文件已下载完成，正在准备安装。",
    installing: "校验驱动版本并安装到本机。",
    retrying: progress.message,
    verifying: "确认 Chrome 能正常启动，并与驱动连接。",
    complete: "正在确认准备结果。",
    error: progress.message,
  };
  const description = running ? descriptions[progress.stage]
    : success ? (checking ? "可以继续登录 12306，准备查询余票。" : "现在可以检查运行环境。")
      : "请根据下方原因处理后重试。";
  const Icon = running ? LoaderCircle : success ? Check : CircleAlert;

  return <Modal open={open} centered title={title} width={560} closable={false} className="railwatch-dialog environment-progress-dialog"
    onCancel={onClose} mask={{ closable: false }}
    footer={<div className="environment-progress-footer">
      <span className={running ? "environment-progress-footer-note" : undefined}>{running
        ? <><Info size={14} aria-hidden="true" /><span>下载速度受网络影响，较慢时可用梯子重试。收起后会继续</span></> : success
        ? <><Clock3 size={13} aria-hidden="true" />用时 {duration(elapsed)}</>
        : "关闭后可重新尝试。"}</span>
      <Button type="primary" autoInsertSpace={false} onClick={onClose}>{running ? "收起" : "关闭"}</Button>
    </div>}>
    <section className={`environment-progress ${progress.status}`} aria-label="环境准备进度">
      <div className="environment-progress-hero" aria-live="polite" aria-atomic="true">
        <span className="environment-progress-icon" aria-hidden="true"><Icon size={23} strokeWidth={1.8} /></span>
        <div><h3>{heading}</h3><p>{description}</p></div>
      </div>
      {transferring && <div className="environment-download">
        <div className="environment-download-caption">
          <span>{readingVersions ? "版本信息读取" : "驱动下载"}</span>
          <strong>{percent === null ? <>{bytes(downloaded)}<small>已{transferVerb}</small></> : <>{percent}<small>%</small></>}</strong>
        </div>
        <div className={`environment-download-track${percent === null ? " indeterminate" : ""}`}
          role="progressbar" aria-label={readingVersions ? "版本信息读取进度" : "ChromeDriver 下载进度"} aria-valuemin={0} aria-valuemax={100}
          aria-valuenow={percent ?? undefined} aria-valuetext={percent === null ? `已${transferVerb} ${bytes(downloaded)}，总大小未知` : `${percent}%`}>
          <span style={percent === null ? undefined : { width: `${percent}%` }} />
        </div>
        <dl className="environment-download-metrics">
          <div><dt>{total === null ? "文件大小" : `已${transferVerb} / 总大小`}</dt>
            <dd>{total === null ? "总大小未知" : `${bytes(downloaded)} / ${bytes(total)}`}</dd></div>
          <div><dt>{transferVerb}速度</dt><dd>{speed === null ? (stale ? "等待网络响应" : "计算中") : `${bytes(speed)}/s`}</dd></div>
          <div><dt>预计{transferVerb}剩余</dt><dd>{eta === null ? "暂无法估算" : `约 ${duration(Math.ceil(eta))}`}</dd></div>
        </dl>
        {stale && <p className="environment-transfer-notice"><Clock3 size={13} aria-hidden="true" />暂未收到新数据，传输恢复后更新。</p>}
      </div>}
      {running && <div className="environment-progress-context">
        {progress.source && <div className="environment-progress-source"><Server size={13} aria-hidden="true" /><span>来源</span><span>{progress.source}</span></div>}
        {progress.version && <span className="environment-progress-version">v{progress.version}</span>}
        <span className="environment-progress-timing"><Clock3 size={13} aria-hidden="true" />已用 {duration(elapsed)}</span>
        {!transferring && <span className="environment-progress-estimate">此步骤暂无法估算剩余时间</span>}
      </div>}
      {progress.status === "error" && <div className="environment-progress-error" role="status">
        <span>失败原因</span><p>{progress.message}</p>
      </div>}
    </section>
  </Modal>;
}
