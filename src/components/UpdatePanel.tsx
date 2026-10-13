import { Fragment, useMemo, type CSSProperties, type HTMLAttributes } from "react";
import { ArrowUpRight, Info, LoaderCircle, RefreshCw, RotateCw, ShieldCheck, TriangleAlert, X } from "lucide-react";
import { formatAppVersion } from "../lib/formatSystemStatus";
import { parseReleaseNotes, type ReleaseNoteBlock, type ReleaseNoteSpan } from "../lib/releaseNotes";
import { formatReleaseDate, getUpdateFacts, getUpdateSignal } from "../lib/updateDisplay";
import type { UpdateRuntimeState } from "../types";

export type UpdatePanelProps = {
  state: UpdateRuntimeState;
  statusLabel: string;
  isUpdating: boolean;
  isInstalling: boolean;
  hasManualDownload: boolean;
  onPrimaryAction: () => void;
  onClose: () => void;
  onOpenReleaseNotes?: () => void;
};

type Copy = { title: string; detail: string; footer: string; action: string };

// Release notes originate outside the app; every run is rendered as React text.
function Spans({ spans }: { spans: ReleaseNoteSpan[] }) {
  return spans.map((span, index) => {
    const text = span.code ? <code>{span.text}</code> : span.text;
    return span.strong ? <strong key={index}>{text}</strong> : <Fragment key={index}>{text}</Fragment>;
  });
}

function ReleaseNotes({ notes, date, onOpen }: { notes: string; date: string; onOpen?: () => void }) {
  const { headline, blocks } = useMemo(() => parseReleaseNotes(notes), [notes]);
  const groups: (ReleaseNoteBlock | ReleaseNoteBlock[])[] = [];
  for (const block of blocks) {
    const last = groups.at(-1);
    if (block.kind === "item" && Array.isArray(last)) last.push(block);
    else groups.push(block.kind === "item" ? [block] : block);
  }
  return (
    <section aria-label="本次更新说明" className="rw-update-release">
      <header className="rw-update-release-head">
        <h3>本次更新</h3>
        {date ? <span>{date}发布</span> : null}
      </header>
      {headline ? <p className="rw-update-release-headline">{headline}</p> : null}
      {groups.length ? (
        <div className="rw-update-release-content">
          {groups.map((group, index) =>
            Array.isArray(group) ? (
              <ul key={index}>{group.map((item, itemIndex) => <li key={itemIndex}><Spans spans={item.spans} /></li>)}</ul>
            ) : group.kind === "heading" ? (
              <h4 key={index}><Spans spans={group.spans} /></h4>
            ) : (
              <p key={index}><Spans spans={group.spans} /></p>
            ),
          )}
        </div>
      ) : headline ? null : <p className="rw-update-release-empty">此版本暂无更新说明</p>}
      {onOpen ? (
        <button className="rw-update-release-link" onClick={onOpen} type="button">
          查看完整更新日志<ArrowUpRight aria-hidden="true" size={13} />
        </button>
      ) : null}
    </section>
  );
}

/**
 * The update as a departure: the installed version is the origin, the new one
 * the destination, and the download travels the track between them.
 */
export function UpdatePanel({ state, statusLabel, isUpdating, isInstalling, hasManualDownload, onPrimaryAction, onClose, onOpenReleaseNotes }: UpdatePanelProps) {
  const checking = state.phase === "checking" || (isUpdating && !["available", "downloading", "downloaded"].includes(state.phase));
  const phase = checking ? "checking" : state.phase;
  const downloaded = phase === "downloaded";
  const downloading = phase === "downloading";
  const manual = phase === "available" && hasManualDownload;
  const preparing = phase === "available" && !manual;
  const upToDate = phase === "not-available";
  const success = state.result?.ok ? state.result : undefined;
  const latestVersion = state.latestVersion || success?.latestVersion || "";
  const releaseNotes = state.releaseNotes || success?.releaseNotes || "";
  const error = state.error || (phase === "error" && state.result && !state.result.ok ? state.result.error : "");
  const percent = downloaded ? 100 : downloading && Number.isFinite(state.downloadPercent)
    ? Math.min(100, Math.max(0, state.downloadPercent!))
    : undefined;
  const showProgress = checking || downloading || downloaded || preparing;
  const signal = getUpdateSignal({ ...state, phase }, isInstalling);
  const facts = getUpdateFacts({ ...state, phase });

  const copy = ({
    idle: { title: "尚未检查更新", detail: "检查新版本，让 RailWatch 保持最新。", footer: "当前版本仍可继续使用", action: "检查更新" },
    checking: { title: "正在检查更新", detail: "正在获取最新版本信息，请稍候。", footer: "你可以继续使用 RailWatch", action: "收起" },
    available: manual
      ? { title: "发现新版本", detail: "前往发布页下载 macOS 安装包。", footer: "下载后按安装说明更新", action: "前往下载" }
      : { title: "发现新版本", detail: "正在准备下载更新，请稍候。", footer: "更新将在后台下载", action: "收起" },
    downloading: { title: "正在下载更新", detail: "在后台下载，你可以继续使用 RailWatch。", footer: "下载完成后可重启安装", action: "收起" },
    downloaded: isInstalling
      ? { title: "正在准备安装", detail: "正在检查运行中的任务与订单，请稍候。", footer: "正在执行安装前检查", action: "准备安装中" }
      : { title: "更新已准备好", detail: "新版本已下载完成，重启后完成安装。", footer: "稍后也可从这里安装", action: "立即重启安装" },
    "not-available": { title: "已是最新版本", detail: "你正在使用最新版本的 RailWatch。", footer: "已完成更新检查", action: "完成" },
    error: { title: "更新未能完成", detail: "请检查网络连接后重试。", footer: "当前版本仍可继续使用", action: "重新检查" },
  } satisfies Record<UpdateRuntimeState["phase"], Copy>)[phase];

  const origin = formatAppVersion(state.currentVersion);
  const destination = upToDate
    ? formatAppVersion(latestVersion || state.currentVersion)
    : latestVersion && phase !== "idle" && !checking ? formatAppVersion(latestVersion) : "";
  const destinationText = destination || (checking ? "查询中" : phase === "idle" ? "待检查" : "—");
  const destinationTone = !destination ? "pending" : downloaded || upToDate ? "go" : phase === "error" ? "dim" : "led";
  const track = downloaded || upToDate ? "arrived" : percent !== undefined ? "moving" : showProgress ? "scanning" : "parked";
  const progress: HTMLAttributes<HTMLDivElement> = showProgress ? {
    role: "progressbar",
    "aria-label": downloaded ? "更新下载完成" : checking ? "检查更新进度" : "更新下载进度",
    "aria-valuemin": 0,
    "aria-valuemax": 100,
    "aria-valuenow": percent === undefined ? undefined : Math.round(percent),
    "aria-valuetext": percent === undefined ? copy.title : `${Math.round(percent)}%`,
  } : { "aria-hidden": true };

  const closeAction = checking || downloading || upToDate || preparing;
  const PrimaryIcon = isInstalling ? LoaderCircle : downloaded ? RotateCw : manual ? ArrowUpRight : RefreshCw;
  const detail = phase === "error" && error ? "" : copy.detail;
  const showNotes = Boolean(latestVersion) && (phase === "available" || downloading || downloaded);

  return (
    <section aria-label="软件更新" className={`rw-update-panel rw-update-${signal.tone}`} role="dialog">
      <div className="rw-update-board">
        <header className="rw-update-kicker">
          <h2>软件更新</h2>
          <span className="rw-update-pill" role="status" title={statusLabel}>
            <i aria-hidden="true" className={`lamp ${signal.tone}${signal.live ? " live" : ""}`} />
            {copy.title}
          </span>
          <button aria-label="收起更新面板" className="rw-update-close" onClick={onClose} type="button">
            <X aria-hidden="true" size={16} />
          </button>
        </header>

        <div className={`rw-update-route${Math.max(origin.length, destinationText.length) > 8 ? " compact" : ""}`}>
          <div className="rw-update-station">
            <strong>{origin}</strong>
            <small>当前版本</small>
          </div>
          <div
            {...progress}
            className={`rw-update-track ${track}`}
            style={{ "--update-progress": (percent ?? 0) / 100 } as CSSProperties}
          >
            {percent !== undefined ? <em aria-hidden="true">{Math.round(percent)}%</em> : null}
            <i aria-hidden="true" className="rw-update-track-fill" />
          </div>
          <div className="rw-update-station rw-update-destination">
            {/* Keyed so a newly found version flips in like a split-flap display. */}
            <strong className={destinationTone} key={destinationText}>{destinationText}</strong>
            <small>{upToDate || !destination ? "最新版本" : "新版本"}</small>
          </div>
        </div>

        {facts.length ? (
          <dl aria-label="下载详情" className="rw-update-facts">
            {facts.map((fact) => (
              <div key={fact.label}>
                <dt>{fact.label}</dt>
                <dd>{fact.value}</dd>
              </div>
            ))}
          </dl>
        ) : null}
      </div>

      <div className="rw-update-stub">
        <div className="rw-update-body">
          {detail ? <p className="rw-update-detail">{detail}</p> : null}
          {error ? (
            <p className={`rw-update-note ${downloaded ? "warning" : "error"}`} role="alert">
              <TriangleAlert aria-hidden="true" size={15} />
              <span>{error}</span>
            </p>
          ) : downloaded && !isInstalling ? (
            <p className="rw-update-note ready">
              <ShieldCheck aria-hidden="true" size={15} />
              <span>安装前会检查正在运行的任务与订单。</span>
            </p>
          ) : null}
          {showNotes ? (
            <ReleaseNotes notes={releaseNotes} date={formatReleaseDate(success?.publishedAt)} onOpen={onOpenReleaseNotes} />
          ) : null}
        </div>

        <footer className="rw-update-footer">
          <span className="rw-update-footer-note">
            <Info aria-hidden="true" size={13} />
            {copy.footer}
          </span>
          <div className="rw-update-actions">
            {downloaded ? <button className="rw-update-button" onClick={onClose} type="button">稍后</button> : null}
            <button
              className={`rw-update-button${closeAction ? "" : " primary"}`}
              disabled={!closeAction && (isUpdating || isInstalling)}
              onClick={closeAction ? onClose : onPrimaryAction}
              type="button"
            >
              {closeAction ? null : <PrimaryIcon aria-hidden="true" className={isInstalling ? "rw-update-spinner" : undefined} size={14} />}
              {copy.action}
            </button>
          </div>
        </footer>
      </div>
    </section>
  );
}
