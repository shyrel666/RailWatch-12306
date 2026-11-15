import { copyFileSync, existsSync, mkdirSync, renameSync, rmSync, unlinkSync } from "node:fs";
import { rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

export const APP_SLUG = "railwatch-12306";
export const ELECTRON_USER_DATA_DIRNAME = "electron";
export const UPDATER_CACHE_DIRNAME = "railwatch-12306-electron-updater";
export const WINDOW_STATE_FILE = "window-state.json";
export const UPDATER_ID_FILE = ".updaterId";

export type AppDataPathOptions = {
  platform?: NodeJS.Platform;
  env?: NodeJS.ProcessEnv;
  homeDir?: string;
};

export type AppPathHost = {
  getPath: (name: "userData" | "home") => string;
  setPath: (name: "userData", value: string) => void;
};

export type SessionClearTarget = {
  clearStorageData?: () => Promise<void>;
  clearCache?: () => Promise<void>;
};

export type TrayCopy = {
  title: string;
  message: string;
};

/** Resolve the unified per-user local data root matching Python's get_data_path(). */
export function resolveRuntimeDataDir(options: AppDataPathOptions = {}): string {
  const platform = options.platform ?? process.platform;
  const env = options.env ?? process.env;
  const homeDir = options.homeDir ?? os.homedir();
  if (platform === "win32") {
    const localBase = env.LOCALAPPDATA || path.join(homeDir, "AppData", "Local");
    return path.join(localBase, APP_SLUG);
  }
  if (platform === "darwin") {
    return path.join(homeDir, "Library", "Application Support", APP_SLUG);
  }
  const xdgBase = env.XDG_DATA_HOME || path.join(homeDir, ".local", "share");
  return path.join(xdgBase, APP_SLUG);
}

/** Keep Chromium/Electron userData inside a dedicated subdirectory under the runtime root. */
export function resolveElectronUserDataDir(options: AppDataPathOptions = {}): string {
  return path.join(resolveRuntimeDataDir(options), ELECTRON_USER_DATA_DIRNAME);
}

/** Resolve electron-updater's downloaded package cache directory on each platform. */
export function resolveUpdaterCacheDir(options: AppDataPathOptions = {}): string {
  const platform = options.platform ?? process.platform;
  const env = options.env ?? process.env;
  const homeDir = options.homeDir ?? os.homedir();
  if (platform === "win32") {
    const localBase = env.LOCALAPPDATA || path.join(homeDir, "AppData", "Local");
    return path.join(localBase, UPDATER_CACHE_DIRNAME);
  }
  if (platform === "darwin") {
    return path.join(homeDir, "Library", "Caches", UPDATER_CACHE_DIRNAME);
  }
  const cacheBase = env.XDG_CACHE_HOME || path.join(homeDir, ".cache");
  return path.join(cacheBase, UPDATER_CACHE_DIRNAME);
}

function migrateLegacyFile(sourcePath: string, destPath: string): void {
  if (!existsSync(sourcePath) || existsSync(destPath)) return;
  try {
    renameSync(sourcePath, destPath);
    return;
  } catch {
    // Fall back to copy + unlink when moving across volumes or permissions differ.
  }
  try {
    copyFileSync(sourcePath, destPath);
    try {
      unlinkSync(sourcePath);
    } catch {
      // Keep the copied destination even if the legacy source cannot be removed.
    }
  } catch {
    // Migration is best-effort so startup never aborts on legacy leftovers.
  }
}

/** Point Electron userData inside the unified data directory and migrate key metadata files. */
export function configureUnifiedUserData(
  appHost: AppPathHost,
  options: AppDataPathOptions = {},
): { legacyUserDataDir: string; userDataDir: string } {
  const legacyUserDataDir = appHost.getPath("userData");
  const targetUserDataDir = resolveElectronUserDataDir(options);
  try {
    mkdirSync(targetUserDataDir, { recursive: true });
    if (legacyUserDataDir && path.resolve(legacyUserDataDir) !== path.resolve(targetUserDataDir) && existsSync(legacyUserDataDir)) {
      for (const fileName of [WINDOW_STATE_FILE, UPDATER_ID_FILE]) {
        migrateLegacyFile(path.join(legacyUserDataDir, fileName), path.join(targetUserDataDir, fileName));
      }
    }
  } catch {
    // Let Electron still initialize userData even if migration hit a filesystem edge case.
  }
  appHost.setPath("userData", targetUserDataDir);
  return { legacyUserDataDir, userDataDir: targetUserDataDir };
}

/** Clear Electron-owned persisted state and updater cache during full data reset. */
export async function clearElectronLocalData(options: {
  userDataDir: string;
  updaterCacheDir?: string;
  clearUpdaterCache?: boolean;
  session?: SessionClearTarget | null;
}): Promise<void> {
  try {
    rmSync(path.join(options.userDataDir, WINDOW_STATE_FILE), { force: true });
  } catch {
    // Best-effort cleanup of persisted window state.
  }

  if (options.session) {
    const tasks: Array<Promise<void>> = [];
    if (typeof options.session.clearStorageData === "function") {
      tasks.push(options.session.clearStorageData());
    }
    if (typeof options.session.clearCache === "function") {
      tasks.push(options.session.clearCache());
    }
    if (tasks.length > 0) {
      await Promise.allSettled(tasks);
    }
  }

  if (options.clearUpdaterCache && options.updaterCacheDir) {
    try {
      await rm(options.updaterCacheDir, { recursive: true, force: true });
    } catch {
      // Ignore locked temporary updater artifacts; user can still continue using the app.
    }
  }
}

export function trayIconFilename(platform: NodeJS.Platform = process.platform): string {
  if (platform === "darwin") return "trayTemplate.png";
  return platform === "win32" ? "icon.ico" : "icon.png";
}

/** On macOS, NSStatusItem with a menu treats clicks as menu-open rather than double-click restore. */
export function usesTrayMenuOnly(platform: NodeJS.Platform = process.platform): boolean {
  return platform === "darwin";
}

export function trayCloseNotice(platform: NodeJS.Platform = process.platform): TrayCopy {
  if (platform === "darwin") {
    return {
      title: "已启用关闭到菜单栏",
      message: "关闭窗口后 RailWatch 会在顶部菜单栏继续运行。\n点击菜单栏图标并选择“显示窗口”可重新打开；也可在菜单中停止监控或退出。",
    };
  }
  return {
    title: "已启用关闭到托盘",
    message: "关闭窗口后 RailWatch 会在托盘继续运行。\n双击托盘图标可重新打开；通过托盘菜单可停止监控或退出。",
  };
}
