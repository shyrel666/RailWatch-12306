import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { describe, expect, test, vi } from "vitest";
import {
  clearElectronLocalData,
  configureUnifiedUserData,
  resolveElectronUserDataDir,
  resolveRuntimeDataDir,
  resolveUpdaterCacheDir,
  trayCloseNotice,
  trayIconFilename,
  usesTrayMenuOnly,
} from "../appDataPaths";

const root = path.resolve(__dirname, "..", "..");

function readPngDimensions(filePath: string): { width: number; height: number } {
  const bytes = readFileSync(filePath);
  // PNG signature + IHDR chunk starts at byte 16 for width/height big-endian uint32.
  expect(bytes.subarray(0, 8)).toEqual(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]));
  return {
    width: bytes.readUInt32BE(16),
    height: bytes.readUInt32BE(20),
  };
}

describe("appDataPaths", () => {
  test("unifies Electron userData under the runtime data root per platform", () => {
    const winEnv = { LOCALAPPDATA: "C:\\Users\\Alice\\AppData\\Local" } as NodeJS.ProcessEnv;
    expect(resolveRuntimeDataDir({ platform: "win32", env: winEnv, homeDir: "C:\\Users\\Alice" }))
      .toBe(path.join("C:\\Users\\Alice\\AppData\\Local", "railwatch-12306"));
    expect(resolveElectronUserDataDir({ platform: "win32", env: winEnv, homeDir: "C:\\Users\\Alice" }))
      .toBe(path.join("C:\\Users\\Alice\\AppData\\Local", "railwatch-12306", "electron"));
    expect(resolveUpdaterCacheDir({ platform: "win32", env: winEnv, homeDir: "C:\\Users\\Alice" }))
      .toBe(path.join("C:\\Users\\Alice\\AppData\\Local", "railwatch-12306-electron-updater"));

    expect(resolveElectronUserDataDir({ platform: "darwin", env: {}, homeDir: "/Users/alice" }))
      .toBe(path.join("/Users/alice", "Library", "Application Support", "railwatch-12306", "electron"));
    expect(resolveUpdaterCacheDir({ platform: "darwin", env: {}, homeDir: "/Users/alice" }))
      .toBe(path.join("/Users/alice", "Library", "Caches", "railwatch-12306-electron-updater"));

    expect(resolveElectronUserDataDir({
      platform: "linux",
      env: { XDG_DATA_HOME: "/home/alice/.data" } as NodeJS.ProcessEnv,
      homeDir: "/home/alice",
    })).toBe(path.join("/home/alice/.data", "railwatch-12306", "electron"));
  });

  test("migrates window-state.json and .updaterId from legacy userData and sets userData path", () => {
    const tmp = mkdtempSync(path.join(os.tmpdir(), "railwatch-userdata-"));
    try {
      const legacyDir = path.join(tmp, "roaming", "railwatch-12306-electron");
      const localBase = path.join(tmp, "local");
      mkdirSync(legacyDir, { recursive: true });
      writeFileSync(path.join(legacyDir, "window-state.json"), JSON.stringify({ theme: "dark", width: 1200 }), "utf8");
      writeFileSync(path.join(legacyDir, ".updaterId"), "updater-uuid-123", "utf8");

      let currentUserData = legacyDir;
      const appHost = {
        getPath: (name: "userData" | "home") => (name === "userData" ? currentUserData : tmp),
        setPath: (_name: "userData", value: string) => { currentUserData = value; },
      };

      const result = configureUnifiedUserData(appHost, {
        platform: "win32",
        env: { LOCALAPPDATA: localBase } as NodeJS.ProcessEnv,
        homeDir: tmp,
      });

      const expectedTarget = path.join(localBase, "railwatch-12306", "electron");
      expect(result).toEqual({ legacyUserDataDir: legacyDir, userDataDir: expectedTarget });
      expect(currentUserData).toBe(expectedTarget);
      expect(readFileSync(path.join(expectedTarget, "window-state.json"), "utf8")).toContain("dark");
      expect(readFileSync(path.join(expectedTarget, ".updaterId"), "utf8")).toBe("updater-uuid-123");
      expect(existsSync(path.join(legacyDir, "window-state.json"))).toBe(false);
    } finally {
      rmSync(tmp, { recursive: true, force: true });
    }
  });

  test("does not overwrite newer unified files during migration", () => {
    const tmp = mkdtempSync(path.join(os.tmpdir(), "railwatch-nomigrate-"));
    try {
      const legacyDir = path.join(tmp, "legacy");
      const localBase = path.join(tmp, "local");
      const targetDir = path.join(localBase, "railwatch-12306", "electron");
      mkdirSync(legacyDir, { recursive: true });
      mkdirSync(targetDir, { recursive: true });
      writeFileSync(path.join(legacyDir, "window-state.json"), '{"theme":"light"}', "utf8");
      writeFileSync(path.join(targetDir, "window-state.json"), '{"theme":"dark"}', "utf8");

      const appHost = {
        getPath: () => legacyDir,
        setPath: vi.fn(),
      };
      configureUnifiedUserData(appHost, {
        platform: "win32",
        env: { LOCALAPPDATA: localBase } as NodeJS.ProcessEnv,
        homeDir: tmp,
      });

      expect(readFileSync(path.join(targetDir, "window-state.json"), "utf8")).toBe('{"theme":"dark"}');
    } finally {
      rmSync(tmp, { recursive: true, force: true });
    }
  });

  test("clearElectronLocalData cleans window-state.json, session storage/cache, and updater cache", async () => {
    const tmp = mkdtempSync(path.join(os.tmpdir(), "railwatch-clear-electron-"));
    try {
      const userDataDir = path.join(tmp, "railwatch-12306", "electron");
      const updaterCacheDir = path.join(tmp, "railwatch-12306-electron-updater");
      mkdirSync(userDataDir, { recursive: true });
      mkdirSync(path.join(updaterCacheDir, "pending"), { recursive: true });
      writeFileSync(path.join(userDataDir, "window-state.json"), '{"width":1100}', "utf8");
      writeFileSync(path.join(updaterCacheDir, "pending", "setup.exe"), "binary", "utf8");

      const clearStorageData = vi.fn(async () => undefined);
      const clearCache = vi.fn(async () => undefined);
      await clearElectronLocalData({
        userDataDir,
        updaterCacheDir,
        clearUpdaterCache: true,
        session: { clearStorageData, clearCache },
      });

      expect(existsSync(path.join(userDataDir, "window-state.json"))).toBe(false);
      expect(clearStorageData).toHaveBeenCalledTimes(1);
      expect(clearCache).toHaveBeenCalledTimes(1);
      expect(existsSync(updaterCacheDir)).toBe(false);
    } finally {
      rmSync(tmp, { recursive: true, force: true });
    }
  });

  test("selects platform tray assets, menu-only mode, and platform copy", () => {
    expect(trayIconFilename("darwin")).toBe("trayTemplate.png");
    expect(trayIconFilename("win32")).toBe("icon.ico");
    expect(trayIconFilename("linux")).toBe("icon.png");

    expect(usesTrayMenuOnly("darwin")).toBe(true);
    expect(usesTrayMenuOnly("win32")).toBe(false);

    const macCopy = trayCloseNotice("darwin");
    expect(macCopy.title).toBe("已启用关闭到菜单栏");
    expect(macCopy.message).toContain("显示窗口");
    expect(macCopy.message).not.toContain("双击");

    const winCopy = trayCloseNotice("win32");
    expect(winCopy.title).toBe("已启用关闭到托盘");
    expect(winCopy.message).toContain("双击托盘图标");
  });

  test("bundles macOS 1x/2x template tray icons and NSIS uninstall data-cleanup hooks", () => {
    const tray1x = path.join(root, "assets", "images", "trayTemplate.png");
    const tray2x = path.join(root, "assets", "images", "trayTemplate@2x.png");
    expect(readPngDimensions(tray1x)).toEqual({ width: 18, height: 18 });
    expect(readPngDimensions(tray2x)).toEqual({ width: 36, height: 36 });

    const builderYml = readFileSync(path.join(root, "electron-builder.yml"), "utf8");
    expect(builderYml).toContain("assets/images/trayTemplate.png");
    expect(builderYml).toContain("assets/images/trayTemplate@2x.png");
    expect(builderYml).toContain("include: build/installer.nsh");

    const nsh = readFileSync(path.join(root, "build", "installer.nsh"), "utf8");
    expect(nsh).toContain("!ifdef BUILD_UNINSTALLER");
    expect(nsh).toContain("!macro customUnWelcomePage");
    expect(nsh).toContain("!macro customUnInstall");
    expect(nsh).toContain("同时删除本地配置、12306 登录数据与更新缓存");
    expect(nsh).toContain("${isUpdated}");
    expect(nsh).toContain("--delete-app-data");
    expect(nsh).toContain("$LOCALAPPDATA\\railwatch-12306");
    expect(nsh).toContain("$LOCALAPPDATA\\railwatch-12306-electron-updater");
    expect(nsh).toContain("$APPDATA\\railwatch-12306-electron");
  });
});
