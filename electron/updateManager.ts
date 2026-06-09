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

export type UpdateRuntimeState = {
  phase: UpdatePhase;
  currentVersion: string;
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
  quitAndInstall(isSilent?: boolean, isForceRunAfter?: boolean): void;
};

type UpdateManagerOptions = {
  currentVersion: string;
  updater: UpdaterLike;
  enabled: boolean;
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

export function mapUpdateInfoToCheckSuccess(currentVersion: string, info: UpdaterInfo): UpdateCheckSuccess {
  const latestVersion = info.version;
  return {
    ok: true,
    currentVersion,
    latestVersion,
    hasUpdate: currentVersion !== latestVersion,
    releaseName: info.releaseName || latestVersion,
    releaseNotes: typeof info.releaseNotes === "string" ? info.releaseNotes : "",
    publishedAt: info.releaseDate || "",
    releaseUrl: "",
    assets: [],
    source: "updater",
  };
}

function buildFailure(currentVersion: string, error: string, code: UpdateCheckFailure["code"] = "unknown"): UpdateCheckFailure {
  return { ok: false, currentVersion, error, code };
}

function formatUpdateError(error: unknown): string {
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
  const { currentVersion, updater, enabled, onStateChange, onUpdateDownloaded } = options;
  let state: UpdateRuntimeState = { phase: "idle", currentVersion };

  const publish = (next: UpdateRuntimeState) => {
    state = next;
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
      result: mapUpdateInfoToCheckSuccess(currentVersion, info),
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
      result: mapUpdateInfoToCheckSuccess(currentVersion, info),
    });
    onUpdateDownloaded?.(info);
  });

  updater.on("error", (error: Error) => {
    const message = formatUpdateError(error);
    publish({
      ...state,
      phase: "error",
      error: message,
      result: buildFailure(currentVersion, message, "network"),
    });
  });

  return {
    getState(): UpdateRuntimeState {
      return state;
    },
    async checkForUpdates(checkOptions: { force?: boolean } = {}): Promise<UpdateCheckResult> {
      void checkOptions.force;
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
          "network",
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
        });
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
    installUpdate(): void {
      if (state.phase !== "downloaded") {
        return;
      }
      updater.quitAndInstall(false, true);
    },
  };
}

export type UpdateManager = ReturnType<typeof createUpdateManager>;
