import { describe, expect, it } from "vitest";
import {
  LATEST_MAC_RELEASE_URL,
  formatMacArchLabel,
  getUpdateFacts,
  hasDirectManualDownload,
  isRosettaMacApp,
  resolveNativeArm64DownloadUrl,
} from "./updateDisplay";
import { getUpdateStatusLabel } from "./useAppUpdate";
import type { UpdateRuntimeState } from "../types";

describe("macOS DMG & Rosetta update display helpers", () => {
  it("flags Rosetta translation only on macOS", () => {
    expect(
      isRosettaMacApp({
        appVersion: "1.0.8",
        electronVersion: "39.0.0",
        chromeVersion: "130.0.0",
        nodeVersion: "22.0.0",
        platform: "darwin",
        arch: "x64",
        runningUnderARM64Translation: true,
      }),
    ).toBe(true);

    expect(
      isRosettaMacApp({
        appVersion: "1.0.8",
        electronVersion: "39.0.0",
        chromeVersion: "130.0.0",
        nodeVersion: "22.0.0",
        platform: "win32",
        arch: "x64",
        runningUnderARM64Translation: true,
      }),
    ).toBe(false);

    expect(
      isRosettaMacApp({
        appVersion: "1.0.8",
        electronVersion: "39.0.0",
        chromeVersion: "130.0.0",
        nodeVersion: "22.0.0",
        platform: "darwin",
        arch: "arm64",
        runningUnderARM64Translation: false,
      }),
    ).toBe(false);
  });

  it("formats direct manual DMG status, size facts, and native arm64 download fallbacks", () => {
    const manualDirectState: UpdateRuntimeState = {
      phase: "available",
      currentVersion: "1.0.7",
      latestVersion: "1.0.8",
      installMode: "manual",
      packageSize: 104_857_600,
      result: {
        ok: true,
        currentVersion: "1.0.7",
        latestVersion: "1.0.8",
        hasUpdate: true,
        releaseName: "1.0.8",
        releaseNotes: "",
        publishedAt: "",
        releaseUrl: "https://github.com/shyrel666/RailWatch-12306/releases/tag/v1.0.8",
        downloadUrl: "https://github.com/shyrel666/RailWatch-12306/releases/download/v1.0.8/RailWatch-12306-1.0.8-arm64.dmg",
        targetArch: "arm64",
        assets: [],
        source: "updater",
      },
    };

    expect(hasDirectManualDownload(manualDirectState)).toBe(true);
    expect(formatMacArchLabel("arm64")).toBe("Apple Silicon (arm64)");
    expect(getUpdateStatusLabel(manualDirectState)).toContain("可直接下载 macOS (Apple Silicon (arm64)) 安装包");
    expect(getUpdateFacts(manualDirectState)).toEqual([{ label: "安装包", value: "100.0 MB" }]);
    expect(resolveNativeArm64DownloadUrl(manualDirectState)).toBe(
      "https://github.com/shyrel666/RailWatch-12306/releases/download/v1.0.8/RailWatch-12306-1.0.8-arm64.dmg",
    );

    const idleState: UpdateRuntimeState = { phase: "idle", currentVersion: "1.0.8", installMode: "manual" };
    expect(resolveNativeArm64DownloadUrl(idleState)).toBe(LATEST_MAC_RELEASE_URL);

    const x64State: UpdateRuntimeState = {
      ...manualDirectState,
      result: manualDirectState.result?.ok
        ? {
            ...manualDirectState.result,
            targetArch: "x64",
            downloadUrl:
              "https://github.com/shyrel666/RailWatch-12306/releases/download/v1.0.8/RailWatch-12306-1.0.8-x64.dmg",
          }
        : manualDirectState.result,
    };
    expect(resolveNativeArm64DownloadUrl(x64State)).toBe(LATEST_MAC_RELEASE_URL);
  });
});
