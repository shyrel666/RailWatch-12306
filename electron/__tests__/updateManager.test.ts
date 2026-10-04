import { EventEmitter } from "node:events";
import { describe, expect, test, vi } from "vitest";
import {
  CHANNEL_FILE_MISSING_MESSAGE,
  createUpdateManager,
  mapUpdateInfoToCheckSuccess,
  shouldEnableAutoUpdate,
  type UpdaterLike,
} from "../updateManager";
import { releaseTagUrl } from "../updateChecker";

function createMockUpdater(): UpdaterLike & EventEmitter {
  const emitter = new EventEmitter();
  return Object.assign(emitter, {
    autoDownload: false,
    autoInstallOnAppQuit: false,
    checkForUpdates: vi.fn(async () => null),
    launchInstaller: vi.fn(async () => undefined),
  });
}

describe("updateManager", () => {
  test("skips auto update outside packaged builds", () => {
    expect(shouldEnableAutoUpdate({ isPackaged: false, devServerUrl: undefined })).toBe(false);
    expect(shouldEnableAutoUpdate({ isPackaged: true, devServerUrl: undefined })).toBe(true);
    expect(shouldEnableAutoUpdate({ isPackaged: true, devServerUrl: "http://127.0.0.1:5173" })).toBe(false);
  });

  test("maps updater info into renderer-friendly check success", () => {
    const mapped = mapUpdateInfoToCheckSuccess("0.1.0", {
      version: "1.2.0",
      releaseName: "RailWatch 1.2.0",
      releaseNotes: "New features",
      releaseDate: "2026-06-01T00:00:00.000Z",
    }, true);

    expect(mapped).toEqual({
      ok: true,
      currentVersion: "0.1.0",
      latestVersion: "1.2.0",
      hasUpdate: true,
      releaseName: "RailWatch 1.2.0",
      releaseNotes: "New features",
      publishedAt: "2026-06-01T00:00:00.000Z",
      releaseUrl: "",
      assets: [],
      source: "updater",
    });
  });

  test("tracks checking, available, downloading, and downloaded phases", async () => {
    const updater = createMockUpdater();
    const states: string[] = [];
    const manager = createUpdateManager({
      currentVersion: "0.1.0",
      updater,
      enabled: true,
      onStateChange: (state) => states.push(state.phase),
    });

    await manager.checkForUpdates();
    expect(states).toContain("checking");

    updater.emit("update-available", { version: "1.2.0", releaseNotes: "Notes" });
    expect(manager.getState().phase).toBe("available");
    expect(manager.getState().latestVersion).toBe("1.2.0");

    updater.emit("download-progress", { percent: 42 });
    expect(manager.getState().phase).toBe("downloading");
    expect(manager.getState().downloadPercent).toBe(42);

    updater.emit("update-downloaded", { version: "1.2.0", releaseNotes: "Notes" });
    expect(manager.getState().phase).toBe("downloaded");
    expect(manager.getState().result?.ok).toBe(true);
    if (manager.getState().result?.ok) {
      expect(manager.getState().result.latestVersion).toBe("1.2.0");
    }
  });

  test("returns up-to-date result when updater reports no update", async () => {
    const updater = createMockUpdater();
    updater.checkForUpdates = vi.fn(async () => {
      updater.emit("update-not-available", { version: "1.2.0" });
      return null;
    });

    const manager = createUpdateManager({
      currentVersion: "1.2.0",
      updater,
      enabled: true,
    });

    const result = await manager.checkForUpdates();
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.hasUpdate).toBe(false);
      expect(result.latestVersion).toBe("1.2.0");
    }
    expect(manager.getState().phase).toBe("not-available");
  });

  test("returns disabled error when auto update is unavailable", async () => {
    const updater = createMockUpdater();
    const manager = createUpdateManager({
      currentVersion: "0.1.0",
      updater,
      enabled: false,
    });

    const result = await manager.checkForUpdates();
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.code).toBe("unknown");
      expect(result.error).toContain("开发环境");
    }
  });

  test("returns a concise message when the updater source returns 404", async () => {
    const updater = createMockUpdater();
    updater.checkForUpdates = vi.fn(async () => {
      throw new Error(
        '404 "method: GET url: https://github.com/railwatch/railwatch-12306/releases.atom\\n\\nPlease double check that your authentication token is correct. Due to security reasons, actual status maybe not reported, but 404."',
      );
    });
    const manager = createUpdateManager({
      currentVersion: "0.1.0",
      updater,
      enabled: true,
    });

    const result = await manager.checkForUpdates();

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error).toBe("无法访问更新源，请确认 GitHub Release 仓库地址和发布资产是否正确。");
      expect(result.error).not.toContain("releases.atom");
    }
    expect(manager.getState().error).toBe("无法访问更新源，请确认 GitHub Release 仓库地址和发布资产是否正确。");
  });

  test("installUpdate waits for launch acknowledgement and coalesces duplicate requests", async () => {
    const updater = createMockUpdater();
    const manager = createUpdateManager({ currentVersion: "0.1.0", updater, enabled: true });

    expect(await manager.installUpdate()).toBe(false);
    expect(updater.launchInstaller).not.toHaveBeenCalled();

    let launched!: () => void;
    updater.launchInstaller = vi.fn(() => new Promise<void>(resolve => { launched = resolve; }));
    updater.emit("update-downloaded", { version: "1.2.0" });
    const pending = manager.installUpdate();
    expect(manager.installUpdate()).toBe(pending);
    let settled = false;
    void pending.then(() => { settled = true; });
    await new Promise(resolve => setImmediate(resolve));
    expect(settled).toBe(false);
    expect(updater.launchInstaller).toHaveBeenCalledOnce();
    launched();
    expect(await pending).toBe(true);
  });

  test.each([false, true])("installUpdate reports synchronous/asynchronous launch failure (async=%s)", async delayed => {
    const updater = createMockUpdater();
    updater.launchInstaller = vi.fn(() => {
      if (!delayed) throw new Error("installer missing");
      return new Promise((_, reject) => setImmediate(() => reject(new Error("installer missing"))));
    });
    const manager = createUpdateManager({ currentVersion: "0.1.0", updater, enabled: true });
    updater.emit("update-downloaded", { version: "1.2.0" });

    expect(await manager.installUpdate()).toBe(false);
    expect(manager.getState().error).toBe("installer missing");
    expect(updater.listenerCount("error")).toBe(1);
    updater.launchInstaller = vi.fn(async () => undefined);
    updater.emit("update-downloaded", { version: "1.2.0" });
    expect(await manager.installUpdate()).toBe(true);
  });

  test("manual mode keeps its install mode through every transition and links the release page", async () => {
    const updater = createMockUpdater();
    const states: string[] = [];
    const manager = createUpdateManager({
      currentVersion: "0.6.0", updater, enabled: true, installMode: "manual", releaseUrlFor: releaseTagUrl,
      onStateChange: (state) => states.push(state.installMode),
    });
    expect(manager.getState().installMode).toBe("manual");
    await manager.checkForUpdates();
    updater.emit("update-available", { version: "0.6.1" });
    updater.emit("error", new Error("offline"));
    updater.emit("update-not-available", { version: "0.6.1" });
    expect(states.length).toBeGreaterThan(3);
    expect(new Set(states)).toEqual(new Set(["manual"]));
    updater.emit("update-available", { version: "0.6.1" });
    const result = manager.getState().result;
    expect(result?.ok && result.releaseUrl).toBe("https://github.com/shyrel666/RailWatch-12306/releases/tag/v0.6.1");
  });

  test("the default install mode is auto", () => {
    expect(createUpdateManager({ currentVersion: "0.6.0", updater: createMockUpdater(), enabled: true }).getState().installMode).toBe("auto");
  });

  test("a release without this platform's metadata is not reported as an unreachable source", async () => {
    const updater = createMockUpdater();
    const missing = Object.assign(new Error("Cannot find latest-mac.yml in the latest release artifacts (https://github.com/x/y/releases/download/v0.6.1/latest-mac.yml): 404"),
      { code: "ERR_UPDATER_CHANNEL_FILE_NOT_FOUND" });
    updater.checkForUpdates = vi.fn(async () => {
      updater.emit("error", missing);
      throw missing;
    });
    const manager = createUpdateManager({ currentVersion: "0.6.0", updater, enabled: true, installMode: "manual" });
    const result = await manager.checkForUpdates();
    expect(result).toMatchObject({ ok: false, code: "no-assets", error: CHANNEL_FILE_MISSING_MESSAGE });
    expect(manager.getState().error).toBe(CHANNEL_FILE_MISSING_MESSAGE);
    expect(updater.checkForUpdates).toHaveBeenCalledOnce();
  });

  test("an updater without acknowledged installation never invokes quitAndInstall", async () => {
    const updater = Object.assign(createMockUpdater(), { launchInstaller: undefined, quitAndInstall: vi.fn() });
    const manager = createUpdateManager({ currentVersion: "0.1.0", updater, enabled: true });
    updater.emit("update-downloaded", { version: "1.2.0" });
    expect(await manager.installUpdate()).toBe(false);
    expect(updater.quitAndInstall).not.toHaveBeenCalled();
    expect(manager.getState().error).toContain("手动安装");
  });
});
