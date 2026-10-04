import { Tooltip } from "antd";
import { ArrowUpCircle, Download } from "lucide-react";
import { useAppUpdate } from "../lib/useAppUpdate";

export function UpdateStatusControl({ appVersion }: { appVersion: string }) {
  const { statusLabel, hasDownloadedUpdate, hasManualDownload, hasPendingUpdate, isUpdating, handlePrimaryAction } =
    useAppUpdate(appVersion);

  const actionLabel = hasDownloadedUpdate ? "立即重启安装" : hasManualDownload ? "前往下载" : isUpdating ? "检查更新中" : "检查更新";
  const buttonClassName = [
    "statusbar-icon-button",
    hasDownloadedUpdate ? "update-ready" : "",
    hasPendingUpdate && !hasDownloadedUpdate ? "update-pending" : "",
    isUpdating ? "update-busy" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <Tooltip title={statusLabel}>
      <button
        aria-label={actionLabel}
        className={buttonClassName}
        disabled={isUpdating}
        onClick={() => void handlePrimaryAction()}
        type="button"
      >
        {hasDownloadedUpdate || hasManualDownload ? <Download size={16} /> : <ArrowUpCircle size={16} />}
      </button>
    </Tooltip>
  );
}
