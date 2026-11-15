import { EventEmitter } from "node:events";
import { describe, expect, it, vi } from "vitest";
import { isAllowedExternalUrl } from "../ipcSecurity";
import {
  LATEST_RELEASE_URL,
  findMacDmgAsset,
  releaseAssetUrl,
  releaseTagUrl,
  resolveMacDmgDownload,
  resolveMacTargetArch,
} from "../updateChecker";
import { createUpdateManager, type UpdaterInfo, type UpdaterLike } from "../updateManager";

function createFakeUpdater() {
  const emitter = new EventEmitter();
  return Object.assign(emitter, {
    autoDownload: true,
    autoInstallOnAppQuit: false,
    checkForUpdates: vi.fn().mockResolvedValue(null),
    launchInstaller: vi.fn().mockResolvedValue(undefined),
  }) as UpdaterLike & EventEmitter;
}

describe("macOS architecture & direct DMG download resolution", () => {
  it("picks arm64 on native Apple Silicon and when Intel builds run under Rosetta", () => {
    expect(resolveMacTargetArch("arm64", false)).toBe("arm64");
    expect(resolveMacTargetArch("x64", false)).toBe("x64");
    expect(resolveMacTargetArch("x64", true)).toBe("arm64");
  });

  it("matches architecture-specific DMG assets from updater metadata without picking zip files", () => {
    const files = [
      { url: "RailWatch-12306-1.0.8-arm64-mac.zip", size: 95_000_000 },
      { url: "RailWatch-12306-1.0.8-x64.dmg", size: 102_000_000 },
      { url: "RailWatch-12306-1.0.8-arm64.dmg", size: 98_500_000 },
    ];

    expect(findMacDmgAsset(files, "arm64")).toEqual({
      fileName: "RailWatch-12306-1.0.8-arm64.dmg",
      url: undefined,
      size: 98_500_000,
    });
    expect(findMacDmgAsset(files, "x64")).toEqual({
      fileName: "RailWatch-12306-1.0.8-x64.dmg",
      url: undefined,
      size: 102_000_000,
    });

    const resolved = resolveMacDmgDownload({
      version: "1.0.8",
      tag: "v1.0.8",
      arch: "arm64",
      files,
    });
    expect(resolved).toEqual({
      downloadUrl: releaseAssetUrl("v1.0.8", "RailWatch-12306-1.0.8-arm64.dmg"),
      targetArch: "arm64",
      packageSize: 98_500_000,
      fileName: "RailWatch-12306-1.0.8-arm64.dmg",
    });
    expect(isAllowedExternalUrl(resolved.downloadUrl)).toBe(true);
  });

  it("synthesizes standard RailWatch DMG filenames when files metadata omits DMGs", () => {
    const resolved = resolveMacDmgDownload({
      version: "v1.2.3",
      arch: "x64",
    });
    expect(resolved.downloadUrl).toBe(
      "https://github.com/shyrel666/RailWatch-12306/releases/download/v1.2.3/RailWatch-12306-1.2.3-x64.dmg",
    );
    expect(resolved.targetArch).toBe("x64");
    expect(isAllowedExternalUrl(resolved.downloadUrl)).toBe(true);
  });

  it("falls back to the latest release page when neither version nor DMG metadata is available", () => {
    const resolved = resolveMacDmgDownload({
      version: "",
      arch: "arm64",
    });
    expect(resolved.downloadUrl).toBe(LATEST_RELEASE_URL);
    expect(isAllowedExternalUrl(resolved.downloadUrl)).toBe(true);
  });

  it("wires direct DMG downloadUrl, targetArch, and DMG packageSize through createUpdateManager", async () => {
    const updater = createFakeUpdater();
    const states: ReturnType<ReturnType<typeof createUpdateManager>["getState"]>[] = [];
    const manager = createUpdateManager({
      currentVersion: "1.0.7",
      updater,
      enabled: true,
      installMode: "manual",
      releaseUrlFor: releaseTagUrl,
      resolveManualDownload: (info) =>
        resolveMacDmgDownload({
          version: info.version,
          tag: info.tag,
          arch: "arm64",
          files: info.files,
        }),
      onStateChange: (state) => states.push(state),
    });

    const info: UpdaterInfo = {
      version: "1.0.8",
      tag: "v1.0.8",
      files: [
        { url: "RailWatch-12306-1.0.8-x64-mac.zip", size: 111_000_000 },
        { url: "RailWatch-12306-1.0.8-x64.dmg", size: 120_000_000 },
        { url: "RailWatch-12306-1.0.8-arm64.dmg", size: 105_000_000 },
      ],
    };

    updater.emit("update-available", info);
    const availableState = manager.getState();
    expect(availableState.packageSize).toBe(105_000_000);
    expect(availableState.result?.ok).toBe(true);
    if (availableState.result?.ok) {
      expect(availableState.result.releaseUrl).toBe(releaseTagUrl("1.0.8"));
      expect(availableState.result.downloadUrl).toBe(
        releaseAssetUrl("v1.0.8", "RailWatch-12306-1.0.8-arm64.dmg"),
      );
      expect(availableState.result.targetArch).toBe("arm64");
    }

    updater.emit("update-not-available", info);
    const notAvailableState = manager.getState();
    expect(notAvailableState.phase).toBe("not-available");
    expect(notAvailableState.result?.ok).toBe(true);
    if (notAvailableState.result?.ok) {
      expect(notAvailableState.result.hasUpdate).toBe(false);
      expect(notAvailableState.result.releaseUrl).toBe("");
      expect(notAvailableState.result.downloadUrl).toBe(
        releaseAssetUrl("v1.0.8", "RailWatch-12306-1.0.8-arm64.dmg"),
      );
      expect(notAvailableState.result.targetArch).toBe("arm64");
    }
    expect(states.length).toBeGreaterThanOrEqual(2);
  });
});
