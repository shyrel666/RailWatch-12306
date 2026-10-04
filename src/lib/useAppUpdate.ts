import { useCallback, useEffect, useState } from "react";
import { railwatchApi } from "./railwatchApi";
import type { UpdateRuntimeState } from "../types";

function manualReleaseUrl(state: UpdateRuntimeState): string {
  if (state.installMode !== "manual" || !state.result?.ok || !state.result.hasUpdate) return "";
  return state.result.releaseUrl;
}

export function getUpdateStatusLabel(state: UpdateRuntimeState): string {
  switch (state.phase) {
    case "checking":
      return "正在检查更新...";
    case "available":
      if (state.installMode === "manual") {
        return state.latestVersion
          ? `发现新版本 ${state.latestVersion}，请前往发布页下载 macOS 安装包`
          : "发现新版本，请前往发布页下载 macOS 安装包";
      }
      return state.latestVersion ? `发现新版本 ${state.latestVersion}，正在准备下载...` : "发现新版本，正在准备下载...";
    case "downloading":
      return state.downloadPercent != null
        ? `正在下载更新 ${Math.round(state.downloadPercent)}%`
        : "正在下载更新...";
    case "downloaded":
      return state.error || (state.latestVersion ? `新版本 ${state.latestVersion} 已下载，等待重启安装` : "更新已下载，等待重启安装");
    case "not-available":
      return "已是最新版本";
    case "error":
      return state.error || "检查更新失败";
    default:
      if (state.result?.ok && state.result.hasUpdate) {
        return `发现新版本 ${state.result.latestVersion}`;
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

export function useAppUpdate(currentVersion: string) {
  const [updateState, setUpdateState] = useState<UpdateRuntimeState>({
    phase: "idle",
    currentVersion,
  });
  const [checking, setChecking] = useState(false);

  useEffect(() => {
    let active = true;

    void railwatchApi
      .getUpdateState()
      .then((state) => {
        if (active) {
          setUpdateState(state);
        }
      })
      .catch(() => undefined);

    const unsubscribe = railwatchApi.onUpdateState((state) => {
      setUpdateState(state);
      if (state.phase !== "checking") {
        setChecking(false);
      }
    });

    return () => {
      active = false;
      unsubscribe();
    };
  }, [currentVersion]);

  const handleCheckUpdate = useCallback(async () => {
    setChecking(true);
    try {
      const result = await railwatchApi.checkUpdate();
      setUpdateState((current) => ({
        ...current,
        result,
        latestVersion: result.ok ? result.latestVersion : current.latestVersion,
        error: result.ok ? undefined : result.error,
        phase: result.ok
          ? result.hasUpdate
            ? current.phase === "downloading" || current.phase === "downloaded"
              ? current.phase
              : "available"
            : "not-available"
          : "error",
      }));
    } catch (error) {
      setUpdateState((current) => ({
        ...current,
        phase: "error",
        error: error instanceof Error ? error.message : "检查更新失败。",
      }));
    } finally {
      setChecking(false);
    }
  }, []);

  const handleInstallUpdate = useCallback(async () => {
    try {
      const result = await railwatchApi.installUpdate();
      if (!result.ok) setUpdateState((current) => ({ ...current, error: result.error || "当前无法安装更新。" }));
    } catch (error) {
      setUpdateState((current) => ({ ...current, error: error instanceof Error ? error.message : "当前无法安装更新。" }));
    }
  }, []);

  const hasDownloadedUpdate = updateState.phase === "downloaded";
  const isUpdating = checking || updateState.phase === "checking" || updateState.phase === "downloading";
  const hasPendingUpdate =
    hasDownloadedUpdate || updateState.phase === "available" || updateState.phase === "downloading";
  const downloadPageUrl = updateState.phase === "available" ? manualReleaseUrl(updateState) : "";
  const hasManualDownload = Boolean(downloadPageUrl);

  const handlePrimaryAction = useCallback(async () => {
    if (hasDownloadedUpdate) {
      await handleInstallUpdate();
      return;
    }
    if (downloadPageUrl) {
      const result = await railwatchApi.openExternal(downloadPageUrl);
      if (!result.ok) setUpdateState((current) => ({ ...current, error: result.error || "无法打开发布页。" }));
      return;
    }
    await handleCheckUpdate();
  }, [hasDownloadedUpdate, downloadPageUrl, handleCheckUpdate, handleInstallUpdate]);

  return {
    updateState,
    statusLabel: getUpdateStatusLabel(updateState),
    hasDownloadedUpdate,
    hasManualDownload,
    hasPendingUpdate,
    isUpdating,
    handleCheckUpdate,
    handleInstallUpdate,
    handlePrimaryAction,
  };
}
