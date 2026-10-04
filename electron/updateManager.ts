import { EventEmitter } from "node:events";
import type { UpdateCheckFailure, UpdateCheckResult, UpdateCheckSuccess } from "./updateChecker";

export type UpdatePhase =
  | "idle"
  | "checking"
  | "available"
  | "downloading"
  | "downloaded"
  | "not-available"
  | "error";

/** auto: download and install in the app; manual: only check and open the release page. */
export type UpdateInstallMode = "auto" | "manual";

export type UpdateRuntimeState = {
  phase: UpdatePhase;
  currentVersion: string;
  installMode: UpdateInstallMode;
  latestVersion?: string;
  releaseNotes?: string;
  downloadPercent?: number;
  error?: string;
  result?: UpdateCheckResult;
};

export type UpdaterInfo = {
  version: string;
  releaseName?: string | null;
  releaseNotes?: string | null;
  releaseDate?: string;
};

export type UpdaterLike = EventEmitter & {
  autoDownload: boolean;
  autoInstallOnAppQuit: boolean;
  checkForUpdates(): Promise<unknown>;
  launchInstaller?(): Promise<void>;
};

type UpdateManagerOptions = {
  currentVersion: string;
  updater: UpdaterLike;
  enabled: boolean;
  installMode?: UpdateInstallMode;
  releaseUrlFor?: (version: string) => string;
  onStateChange?: (state: UpdateRuntimeState) => void;
  onUpdateDownloaded?: (info: UpdaterInfo) => void;
};

type AutoUpdateEnvironment = {
  isPackaged: boolean;
  devServerUrl?: string;
};

export function shouldEnableAutoUpdate(env: AutoUpdateEnvironment): boolean {
  if (!env.isPackaged) {
    return false;
  }
  if (env.devServerUrl) {
    return false;
  }
  return true;
}

export function mapUpdateInfoToCheckSuccess(currentVersion: string, info: UpdaterInfo, hasUpdate: boolean, releaseUrl = ""): UpdateCheckSuccess {
  const latestVersion = info.version;
  return {
    ok: true,
    currentVersion,
    latestVersion,
    hasUpdate,
    releaseName: info.releaseName || latestVersion,
    releaseNotes: typeof info.releaseNotes === "string" ? info.releaseNotes : "",
    publishedAt: info.releaseDate || "",
    releaseUrl,
    assets: [],
    source: "updater",
  };
}

export const CHANNEL_FILE_MISSING_MESSAGE = "最新版本暂未提供本平台安装包，请稍后再检查。";

/** The latest release lacks this platform's metadata (e.g. a single-platform release). */
function isChannelFileMissing(error: unknown): boolean {
  return (error as { code?: unknown } | null)?.code === "ERR_UPDATER_CHANNEL_FILE_NOT_FOUND";
}

function failureCode(error: unknown): UpdateCheckFailure["code"] {
  return isChannelFileMissing(error) ? "no-assets" : "network";
}

function buildFailure(currentVersion: string, error: string, code: UpdateCheckFailure["code"] = "unknown"): UpdateCheckFailure {
  return { ok: false, currentVersion, error, code };
}

function formatUpdateError(error: unknown): string {
  if (isChannelFileMissing(error)) {
    return CHANNEL_FILE_MISSING_MESSAGE;
  }
  const message = error instanceof Error ? error.message : typeof error === "string" ? error : "";
  if (!message) {
    return "检查更新失败。";
  }
  if (/404/i.test(message) && /releases\.atom|github\.com/i.test(message)) {
    return "无法访问更新源，请确认 GitHub Release 仓库地址和发布资产是否正确。";
  }
  return message;
}

export function createUpdateManager(options: UpdateManagerOptions) {
  const { currentVersion, updater, enabled, onStateChange, onUpdateDownloaded, installMode = "auto", releaseUrlFor } = options;
  let state: UpdateRuntimeState = { phase: "idle", currentVersion, installMode };
  let installation: Promise<boolean> | null = null;
  const releaseUrl = (version: string) => releaseUrlFor?.(version) ?? "";

  const publish = (next: Omit<UpdateRuntimeState, "installMode">) => {
    state = { ...next, installMode };
    onStateChange?.(state);
  };

  updater.on("checking-for-update", () => {
    publish({ ...state, phase: "checking", error: undefined });
  });

  updater.on("update-available", (info: UpdaterInfo) => {
    publish({
      phase: "available",
      currentVersion,
      latestVersion: info.version,
      releaseNotes: typeof info.releaseNotes === "string" ? info.releaseNotes : "",
      result: mapUpdateInfoToCheckSuccess(currentVersion, info, true, releaseUrl(info.version)),
    });
  });

  updater.on("update-not-available", (info: UpdaterInfo) => {
    publish({
      phase: "not-available",
      currentVersion,
      latestVersion: info.version,
      result: {
        ok: true,
        currentVersion,
        latestVersion: info.version,
        hasUpdate: false,
        releaseName: info.releaseName || info.version,
        releaseNotes: typeof info.releaseNotes === "string" ? info.releaseNotes : "",
        publishedAt: info.releaseDate || "",
        releaseUrl: "",
        assets: [],
        source: "updater",
      },
    });
  });

  updater.on("download-progress", (progress: { percent?: number }) => {
    publish({
      ...state,
      phase: "downloading",
      downloadPercent: typeof progress.percent === "number" ? progress.percent : undefined,
    });
  });

  updater.on("update-downloaded", (info: UpdaterInfo) => {
    publish({
      phase: "downloaded",
      currentVersion,
      latestVersion: info.version,
      releaseNotes: typeof info.releaseNotes === "string" ? info.releaseNotes : "",
      downloadPercent: 100,
      result: mapUpdateInfoToCheckSuccess(currentVersion, info, true, releaseUrl(info.version)),
    });
    onUpdateDownloaded?.(info);
  });

  updater.on("error", (error: Error) => {
    const message = formatUpdateError(error);
    publish({
      ...state,
      phase: "error",
      error: message,
      result: buildFailure(currentVersion, message, failureCode(error)),
    });
  });

  return {
    getState(): UpdateRuntimeState {
      return state;
    },
    async checkForUpdates(): Promise<UpdateCheckResult> {
      if (!enabled) {
        const failure = buildFailure(currentVersion, "当前为开发环境，自动更新不可用。");
        publish({ ...state, phase: "error", error: failure.error, result: failure });
        return failure;
      }

      publish({ ...state, phase: "checking", error: undefined });
      try {
        await updater.checkForUpdates();
      } catch (error) {
        const failure = buildFailure(
          currentVersion,
          formatUpdateError(error),
          failureCode(error),
        );
        publish({ ...state, phase: "error", error: failure.error, result: failure });
        return failure;
      }

      if (state.result) {
        return state.result;
      }

      if (state.phase === "available" && state.latestVersion) {
        return mapUpdateInfoToCheckSuccess(currentVersion, {
          version: state.latestVersion,
          releaseNotes: state.releaseNotes,
        }, true, releaseUrl(state.latestVersion));
      }

      if (state.phase === "not-available" && state.latestVersion) {
        return {
          ok: true,
          currentVersion,
          latestVersion: state.latestVersion,
          hasUpdate: false,
          releaseName: state.latestVersion,
          releaseNotes: state.releaseNotes || "",
          publishedAt: "",
          releaseUrl: "",
          assets: [],
          source: "updater",
        };
      }

      return {
        ok: true,
        currentVersion,
        latestVersion: currentVersion,
        hasUpdate: false,
        releaseName: currentVersion,
        releaseNotes: "",
        publishedAt: "",
        releaseUrl: "",
        assets: [],
        source: "updater",
      };
    },
    installUpdate(): Promise<boolean> {
      if (installation) return installation;
      if (state.phase !== "downloaded") {
        return Promise.resolve(false);
      }
      // Only the shipped NSIS installer currently has an acknowledged launch
      // path. Never fall back to quitAndInstall, which may quit before failure.
      installation = Promise.resolve().then(async () => {
        try {
          if (!updater.launchInstaller) throw new Error("当前平台不支持自动安装，请手动安装更新。");
          await updater.launchInstaller();
          return true;
        } catch (error) {
          const message = formatUpdateError(error);
          publish({ ...state, phase: "error", error: message, result: buildFailure(currentVersion, message) });
          installation = null;
          return false;
        }
      });
      return installation;
    },
  };
}

export type UpdateManager = ReturnType<typeof createUpdateManager>;
