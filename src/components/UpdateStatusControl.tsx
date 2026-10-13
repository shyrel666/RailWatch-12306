import { useCallback, useEffect, useId, useRef, type CSSProperties } from "react";
import { Button, Popover } from "antd";
import { ArrowDownCircle, Download } from "lucide-react";
import { useAppUpdate, type AppUpdateController } from "../lib/useAppUpdate";
import { useUpdateReadyPrompt } from "../lib/useThemedDialogs";
import type { UpdateRuntimeState } from "../types";
import { UpdatePanel } from "./UpdatePanel";

/** Running downloads draw their progress around the sidebar icon, visible without opening the panel. */
function downloadRing(state: UpdateRuntimeState): number | "indeterminate" | null {
  if (state.phase === "downloading" && Number.isFinite(state.downloadPercent)) {
    return Math.min(100, Math.max(0, state.downloadPercent!));
  }
  return state.phase === "downloading" || (state.phase === "available" && state.installMode !== "manual") ? "indeterminate" : null;
}

function ProgressRing({ value }: { value: number | "indeterminate" }) {
  const indeterminate = value === "indeterminate";
  return (
    <svg aria-hidden="true" className={"update-status-ring" + (indeterminate ? " indeterminate" : "")} viewBox="0 0 32 32">
      <circle cx="16" cy="16" pathLength="100" r="14.25" />
      <circle cx="16" cy="16" pathLength="100" r="14.25" style={{ "--ring-value": indeterminate ? 28 : value } as CSSProperties} />
    </svg>
  );
}

export function UpdateStatusControl({ appVersion, variant = "icon", update }: {
  appVersion: string;
  variant?: "icon" | "button";
  update?: AppUpdateController;
}) {
  const controller = useAppUpdate(appVersion, update);
  const { updateState, statusLabel, hasDownloadedUpdate, hasManualDownload, hasPendingUpdate, isUpdating, isInstalling } = controller;
  const panelId = useId();
  const open = controller.openPanel === panelId;
  const setOpen = useCallback((next: boolean) => {
    controller.setOpenPanel(current => next ? panelId : current === panelId ? null : current);
  }, [controller.setOpenPanel, panelId]);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const showReady = useCallback(() => {
    controller.setOpenPanel(current => current ?? panelId);
  }, [controller.setOpenPanel, panelId]);
  useUpdateReadyPrompt(showReady, variant === "icon");

  const close = useCallback(() => {
    setOpen(false);
    triggerRef.current?.focus({ preventScroll: true });
  }, [setOpen]);
  useEffect(() => {
    if (!open) return;
    const onEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      const dialog = document.getElementById(panelId);
      if (!dialog?.contains(document.activeElement) && document.activeElement !== triggerRef.current) return;
      event.preventDefault();
      event.stopPropagation();
      close();
    };
    document.addEventListener("keydown", onEscape, true);
    return () => document.removeEventListener("keydown", onEscape, true);
  }, [open, close, panelId]);

  const onOpenChange = (next: boolean) => {
    setOpen(next);
    if (next && (updateState.phase === "idle" || updateState.phase === "not-available") && !isUpdating) void controller.handleCheckUpdate();
  };
  const label = hasDownloadedUpdate ? "查看已下载更新" : updateState.phase === "available" ? "查看可用更新" :
    updateState.phase === "downloading" ? "查看更新进度" :
    updateState.phase === "checking" ? "查看更新检查状态" : "检查更新";
  const buttonLabel = hasDownloadedUpdate ? "查看更新" : hasManualDownload ? "前往下载" : updateState.phase === "available" ? "查看更新" :
    updateState.phase === "downloading" ? "查看下载进度" : isUpdating ? "正在检查更新" : "检查更新";
  const releaseUrl = updateState.result?.ok ? updateState.result.releaseUrl : "";
  const ring = downloadRing(updateState);

  return (
    <Popover
      classNames={{ root: "update-popover" }}
      content={
        <div id={panelId}>
          <UpdatePanel
            state={updateState}
            statusLabel={statusLabel}
            isUpdating={isUpdating}
            isInstalling={isInstalling}
            hasManualDownload={hasManualDownload}
            onClose={close}
            onPrimaryAction={() => void controller.handlePrimaryAction()}
            onOpenReleaseNotes={releaseUrl ? () => void controller.handleOpenReleaseNotes() : undefined}
          />
        </div>
      }
      open={open}
      onOpenChange={onOpenChange}
      afterOpenChange={(visible) => {
        if (visible) document.getElementById(panelId)?.querySelector<HTMLButtonElement>(".rw-update-close")?.focus({ preventScroll: true });
      }}
      placement={variant === "icon" ? "topLeft" : "bottomRight"}
      trigger="click"
      arrow={false}
      destroyOnHidden
    >
      {variant === "button" ? (
        <Button
          ref={triggerRef}
          className="update-status-trigger"
          aria-label={label}
          aria-expanded={open}
          aria-controls={open ? panelId : undefined}
          aria-haspopup="dialog"
          icon={<Download aria-hidden="true" size={16} />}
          type="primary"
        >{buttonLabel}</Button>
      ) : (
        <button
          ref={triggerRef}
          aria-label={label}
          aria-expanded={open}
          aria-controls={open ? panelId : undefined}
          aria-haspopup="dialog"
          className={["statusbar-icon-button", "update-status-trigger", hasDownloadedUpdate ? "update-ready" : hasPendingUpdate ? "update-pending" : "", isUpdating ? "update-busy" : "", open ? "update-open" : ""].filter(Boolean).join(" ")}
          title={statusLabel}
          type="button"
        >
          <ArrowDownCircle aria-hidden="true" size={16} />
          {ring !== null ? <ProgressRing value={ring} /> : hasPendingUpdate && <i className="update-status-dot" aria-hidden="true" />}
        </button>
      )}
    </Popover>
  );
}
