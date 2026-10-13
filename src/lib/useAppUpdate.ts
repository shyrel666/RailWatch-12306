import { createContext, useCallback, useContext, useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { formatAppVersion } from "./formatSystemStatus";
import { railwatchApi } from "./railwatchApi";
import type { UpdateRuntimeState } from "../types";

function manualReleaseUrl(state: UpdateRuntimeState): string {
  if (state.installMode !== "manual" || !state.result?.ok || !state.result.hasUpdate) return "";
  return state.result.releaseUrl;
}

export type AppUpdateController = {
  updateState: UpdateRuntimeState;
  statusLabel: string;
  hasDownloadedUpdate: boolean;
  hasManualDownload: boolean;
  hasPendingUpdate: boolean;
  isUpdating: boolean;
  isInstalling: boolean;
  openPanel: string | null;
  setOpenPanel: Dispatch<SetStateAction<string | null>>;
  handleCheckUpdate: () => Promise<void>;
  handleInstallUpdate: () => Promise<void>;
  handlePrimaryAction: () => Promise<void>;
  handleOpenReleaseNotes: () => Promise<void>;
};

export const AppUpdateContext = createContext<AppUpdateController | null>(null);

export function getUpdateStatusLabel(state: UpdateRuntimeState): string {
  const latest = state.latestVersion ? formatAppVersion(state.latestVersion) : "";
  switch (state.phase) {
    case "checking":
      return "正在检查更新…";
    case "available":
      if (state.installMode === "manual") {
        return latest ? `发现新版本 ${latest}，请前往发布页下载 macOS 安装包` : "发现新版本，请前往发布页下载 macOS 安装包";
      }
      return latest ? `发现新版本 ${latest}，正在准备下载…` : "发现新版本，正在准备下载…";
    case "downloading":
      return Number.isFinite(state.downloadPercent)
        ? `正在下载更新 ${Math.round(Math.max(0, Math.min(100, state.downloadPercent!)))}%`
        : "正在下载更新…";
    case "downloaded":
      return state.error || (latest ? `新版本 ${latest} 已下载，等待重启安装` : "更新已下载，等待重启安装");
    case "not-available":
      return "已是最新版本";
    case "error":
      return state.error || "检查更新失败";
    default:
      if (state.result?.ok && state.result.hasUpdate) {
        return `发现新版本 ${formatAppVersion(state.result.latestVersion)}`;
      }
      if (state.result?.ok) {
        return "已是最新版本";
      }
      if (state.result && !state.result.ok) {
        return state.result.error;
      }
      return "尚未检查更新";
  }
}

export function useAppUpdate(currentVersion: string, controller?: AppUpdateController) {
  const context = useContext(AppUpdateContext);
  const shared = controller ?? context;
  const [updateState, setUpdateState] = useState<UpdateRuntimeState>({
    phase: "idle",
    currentVersion,
  });
  const [checking, setChecking] = useState(false);
  const [isInstalling, setInstalling] = useState(false);
  const [openPanel, setOpenPanel] = useState<string | null>(null);
  const stateRef = useRef(updateState);
  const stateRevision = useRef(0);
  const checkingRef = useRef(false);
  const installingRef = useRef(false);
  const publish = useCallback((state: UpdateRuntimeState) => {
    stateRevision.current += 1;
    stateRef.current = state;
    setUpdateState(state);
  }, []);

  useEffect(() => {
    if (shared) return;
    let active = true;
    const initialRevision = stateRevision.current;
    const unsubscribe = railwatchApi.onUpdateState((state) => {
      if (!active) return;
      publish(state);
      if (state.phase !== "checking") {
        setChecking(false);
      }
    });

    void railwatchApi.getUpdateState().then((state) => {
      if (active && stateRevision.current === initialRevision) publish(state);
    }).catch(() => undefined);

    return () => {
      active = false;
      unsubscribe();
    };
  }, [currentVersion, shared, publish]);

  const handleCheckUpdate = useCallback(async () => {
    const state = stateRef.current;
    if (checkingRef.current || installingRef.current || state.phase === "checking" ||
        state.phase === "downloading" || state.phase === "downloaded" ||
        (state.phase === "available" && state.installMode !== "manual")) return;
    checkingRef.current = true;
    setChecking(true);
    publish({ ...state, phase: "checking", error: undefined });
    const revision = stateRevision.current;
    try {
      const result = await railwatchApi.checkUpdate();
      const current = stateRef.current;
      if (stateRevision.current !== revision && current.phase !== "checking") return;
      publish({
        ...current,
        result,
        latestVersion: result.ok ? result.latestVersion : current.latestVersion,
        releaseNotes: result.ok ? result.releaseNotes : current.releaseNotes,
        error: result.ok ? undefined : result.error,
        phase: result.ok
          ? result.hasUpdate
            ? current.phase === "downloading" || current.phase === "downloaded"
              ? current.phase
              : "available"
            : "not-available"
          : "error",
      });
    } catch (error) {
      const current = stateRef.current;
      if (stateRevision.current !== revision && current.phase !== "checking") return;
      publish({
        ...current,
        phase: "error",
        error: error instanceof Error ? error.message : "检查更新失败。",
      });
    } finally {
      checkingRef.current = false;
      setChecking(false);
    }
  }, [publish]);

  const handleInstallUpdate = useCallback(async () => {
    if (installingRef.current || stateRef.current.phase !== "downloaded") return;
    installingRef.current = true;
    setInstalling(true);
    publish({ ...stateRef.current, error: undefined });
    try {
      const result = await railwatchApi.installUpdate();
      publish({ ...stateRef.current, error: result.ok ? undefined : result.error || "当前无法安装更新。" });
    } catch (error) {
      publish({ ...stateRef.current, error: error instanceof Error ? error.message : "当前无法安装更新。" });
    } finally {
      installingRef.current = false;
      setInstalling(false);
    }
  }, [publish]);

  const hasDownloadedUpdate = updateState.phase === "downloaded";
  const isUpdating = checking || updateState.phase === "checking" || updateState.phase === "downloading";
  const hasPendingUpdate =
    hasDownloadedUpdate || updateState.phase === "available" || updateState.phase === "downloading";
  const downloadPageUrl = updateState.phase === "available" ? manualReleaseUrl(updateState) : "";
  const hasManualDownload = Boolean(downloadPageUrl);

  const handlePrimaryAction = useCallback(async () => {
    if (installingRef.current || checkingRef.current) return;
    if (hasDownloadedUpdate) {
      await handleInstallUpdate();
      return;
    }
    if (downloadPageUrl) {
      try {
        const result = await railwatchApi.openExternal(downloadPageUrl);
        if (!result.ok) publish({ ...stateRef.current, error: result.error || "无法打开发布页。" });
      } catch (error) {
        publish({ ...stateRef.current, error: error instanceof Error ? error.message : "无法打开发布页。" });
      }
      return;
    }
    await handleCheckUpdate();
  }, [hasDownloadedUpdate, downloadPageUrl, handleCheckUpdate, handleInstallUpdate, publish]);

  const handleOpenReleaseNotes = useCallback(async () => {
    const result = stateRef.current.result;
    if (!result?.ok || !result.releaseUrl) return;
    try {
      const opened = await railwatchApi.openExternal(result.releaseUrl);
      if (!opened.ok) publish({ ...stateRef.current, error: opened.error || "无法打开更新日志。" });
    } catch (error) {
      publish({ ...stateRef.current, error: error instanceof Error ? error.message : "无法打开更新日志。" });
    }
  }, [publish]);

  return shared ?? {
    updateState,
    statusLabel: getUpdateStatusLabel(updateState),
    hasDownloadedUpdate,
    hasManualDownload,
    hasPendingUpdate,
    isUpdating,
    isInstalling,
    openPanel,
    setOpenPanel,
    handleCheckUpdate,
    handleInstallUpdate,
    handlePrimaryAction,
    handleOpenReleaseNotes,
  };
}
