import { EventEmitter } from "node:events";
import { describe, expect, test, vi } from "vitest";
import {
  createUpdateManager,
  mapUpdateInfoToCheckSuccess,
  shouldEnableAutoUpdate,
  type UpdaterLike,
} from "../updateManager";

function createMockUpdater(): UpdaterLike & EventEmitter {
  const emitter = new EventEmitter();
  return Object.assign(emitter, {
    autoDownload: false,
    autoInstallOnAppQuit: false,
    checkForUpdates: vi.fn(async () => null),
    quitAndInstall: vi.fn(),
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
    });

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

    await manager.checkForUpdates({ force: true });
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

    const result = await manager.checkForUpdates({ force: true });
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

    const result = await manager.checkForUpdates({ force: true });
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.code).toBe("unknown");
      expect(result.error).toContain("开发环境");
    }
  });
});
