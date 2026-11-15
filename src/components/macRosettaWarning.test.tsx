// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App as AntApp } from "antd";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RailWatchApp } from "../App";
import { railwatchApi } from "../lib/railwatchApi";
import { LATEST_MAC_RELEASE_URL } from "../lib/updateDisplay";
import { railwatchStore } from "../store/railwatchStore";
import type { AppInfo, UpdateRuntimeState } from "../types";
import { AboutPage } from "./AboutPage";
import { UpdateStatusControl } from "./UpdateStatusControl";

const ARM64_DMG_URL =
  "https://github.com/shyrel666/RailWatch-12306/releases/download/v1.0.8/RailWatch-12306-1.0.8-arm64.dmg";
const RELEASE_TAG_URL = "https://github.com/shyrel666/RailWatch-12306/releases/tag/v1.0.8";

function rosettaAppInfo(overrides: Partial<AppInfo> = {}): AppInfo {
  return {
    appVersion: "1.0.7",
    electronVersion: "39.2.7",
    chromeVersion: "132.0.0",
    nodeVersion: "22.12.0",
    platform: "darwin",
    arch: "x64",
    runningUnderARM64Translation: true,
    ...overrides,
  };
}

function manualAvailableArm64State(): UpdateRuntimeState {
  return {
    phase: "available",
    currentVersion: "1.0.7",
    latestVersion: "1.0.8",
    installMode: "manual",
    packageSize: 100 * 1024 * 1024,
    result: {
      ok: true,
      currentVersion: "1.0.7",
      latestVersion: "1.0.8",
      hasUpdate: true,
      releaseName: "1.0.8",
      releaseNotes: "",
      publishedAt: "",
      releaseUrl: RELEASE_TAG_URL,
      downloadUrl: ARM64_DMG_URL,
      targetArch: "arm64",
      assets: [],
      source: "updater",
    },
  };
}

function manualUpToDateArm64State(): UpdateRuntimeState {
  return {
    phase: "not-available",
    currentVersion: "1.0.8",
    latestVersion: "1.0.8",
    installMode: "manual",
    result: {
      ok: true,
      currentVersion: "1.0.8",
      latestVersion: "1.0.8",
      hasUpdate: false,
      releaseName: "1.0.8",
      releaseNotes: "",
      publishedAt: "",
      releaseUrl: "",
      downloadUrl: ARM64_DMG_URL,
      targetArch: "arm64",
      assets: [],
      source: "updater",
    },
  };
}

describe("macOS direct DMG download & Rosetta 2 warnings", () => {
  beforeEach(() => {
    railwatchStore.getState().applyRuntimeInfo({
      ...railwatchStore.getState().runtime,
      app_version: "1.0.7",
      app_display_name: "RailWatch 12306",
    });
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("opens direct architecture DMG instead of the generic release page in UpdateStatusControl / UpdatePanel", async () => {
    const state = manualAvailableArm64State();
    vi.spyOn(railwatchApi, "onUpdateState").mockImplementation(() => () => undefined);
    vi.spyOn(railwatchApi, "getUpdateState").mockResolvedValue(state);
    vi.spyOn(railwatchApi, "getAppInfo").mockResolvedValue(rosettaAppInfo());
    const openExternal = vi.spyOn(railwatchApi, "openExternal").mockResolvedValue({ ok: true });

    render(
      <AntApp>
        <UpdateStatusControl appVersion="1.0.7" variant="button" />
      </AntApp>,
    );

    const trigger = await screen.findByRole("button", { name: "查看可用更新" });
    await waitFor(() => expect(trigger.textContent).toContain("下载安装包"));
    fireEvent.click(trigger);

    const dialog = await screen.findByRole("dialog", { name: "软件更新" });
    expect(dialog.textContent).toContain("Apple Silicon (arm64)");
    expect(dialog.textContent).toContain("100.0 MB");

    const primaryButton = dialog.querySelector("button.rw-update-button.primary") as HTMLButtonElement;
    expect(primaryButton).toBeTruthy();
    fireEvent.click(primaryButton);
    await waitFor(() => expect(openExternal).toHaveBeenCalledWith(ARM64_DMG_URL));

    const notesLink = screen.getByRole("button", { name: /查看完整更新日志/ });
    fireEvent.click(notesLink);
    await waitFor(() => expect(openExternal).toHaveBeenCalledWith(RELEASE_TAG_URL));
  });

  it("warns inside UpdatePanel when running under Rosetta even if already on the latest version", async () => {
    const state = manualUpToDateArm64State();
    vi.spyOn(railwatchApi, "onUpdateState").mockImplementation(() => () => undefined);
    vi.spyOn(railwatchApi, "getUpdateState").mockResolvedValue(state);
    vi.spyOn(railwatchApi, "checkUpdate").mockResolvedValue(state.result!);
    vi.spyOn(railwatchApi, "getAppInfo").mockResolvedValue(rosettaAppInfo({ appVersion: "1.0.8" }));
    const openExternal = vi.spyOn(railwatchApi, "openExternal").mockResolvedValue({ ok: true });

    render(
      <AntApp>
        <UpdateStatusControl appVersion="1.0.8" variant="button" />
      </AntApp>,
    );

    const trigger = await screen.findByRole("button", { name: "检查更新" });
    fireEvent.click(trigger);

    const nativeBtn = await screen.findByRole("button", { name: /下载 Apple Silicon \(arm64\) 原生版/ });
    fireEvent.click(nativeBtn);
    await waitFor(() => expect(openExternal).toHaveBeenCalledWith(ARM64_DMG_URL));
  });

  it("shows Rosetta architecture hint and native arm64 download alert in AboutPage on macOS", async () => {
    vi.spyOn(railwatchApi, "onUpdateState").mockImplementation(() => () => undefined);
    vi.spyOn(railwatchApi, "getUpdateState").mockResolvedValue({
      phase: "idle",
      currentVersion: "1.0.7",
      installMode: "manual",
    });
    vi.spyOn(railwatchApi, "getAppInfo").mockResolvedValue(rosettaAppInfo());
    const openExternal = vi.spyOn(railwatchApi, "openExternal").mockResolvedValue({ ok: true });

    render(
      <AntApp>
        <AboutPage />
      </AntApp>,
    );

    await waitFor(() => {
      expect(document.body.textContent).toContain("x64（Rosetta 转译）");
      expect(document.body.textContent).toContain("检测到在 Apple Silicon Mac 上运行了 Intel (x64) 版本");
    });

    const btn = screen.getByRole("button", { name: "下载 Apple Silicon 原生版" });
    fireEvent.click(btn);
    await waitFor(() => expect(openExternal).toHaveBeenCalledWith(LATEST_MAC_RELEASE_URL));
  });

  it("does not show Rosetta alert on non-macOS platforms even when translated flag is set", async () => {
    vi.spyOn(railwatchApi, "onUpdateState").mockImplementation(() => () => undefined);
    vi.spyOn(railwatchApi, "getUpdateState").mockResolvedValue({ phase: "idle", currentVersion: "1.0.7" });
    vi.spyOn(railwatchApi, "getAppInfo").mockResolvedValue(rosettaAppInfo({ platform: "win32" }));

    render(
      <AntApp>
        <AboutPage />
      </AntApp>,
    );

    await waitFor(() => {
      expect(document.body.textContent).toContain("Windows x64");
    });
    expect(document.body.textContent).not.toContain("Rosetta 转译");
    expect(screen.queryByRole("button", { name: "下载 Apple Silicon 原生版" })).toBeNull();
  });

  it("shows a non-blocking startup notification in RailWatchApp under macOS Rosetta translation", async () => {
    vi.spyOn(railwatchApi, "onEvent").mockImplementation(() => () => undefined);
    vi.spyOn(railwatchApi, "onUpdateState").mockImplementation(() => () => undefined);
    vi.spyOn(railwatchApi, "stageDraft").mockImplementation(() => undefined);
    vi.spyOn(railwatchApi, "getUpdateState").mockResolvedValue(manualUpToDateArm64State());
    vi.spyOn(railwatchApi, "getAppInfo").mockResolvedValue(rosettaAppInfo({ appVersion: "1.0.8" }));
    vi.spyOn(railwatchApi, "command").mockImplementation(async (command) => {
      if (command === "loadPreferences") return { auto_rehearsal: false, theme_mode: "system" };
      if (command === "rehearsalHistory") return { items: [] };
      if (command === "getRuntimeInfo") return undefined;
      return undefined;
    });
    const openExternal = vi.spyOn(railwatchApi, "openExternal").mockResolvedValue({ ok: true });

    render(<RailWatchApp />);

    await waitFor(() => {
      expect(document.body.textContent).toContain("当前运行的是 Intel (x64) 版本");
    });

    const downloadBtn = await screen.findByRole("button", { name: "下载 Apple Silicon 原生版" });
    fireEvent.click(downloadBtn);
    await waitFor(() => expect(openExternal).toHaveBeenCalledWith(ARM64_DMG_URL));
  });

  it("does not emit Rosetta startup notification on win32", async () => {
    vi.spyOn(railwatchApi, "onEvent").mockImplementation(() => () => undefined);
    vi.spyOn(railwatchApi, "onUpdateState").mockImplementation(() => () => undefined);
    vi.spyOn(railwatchApi, "stageDraft").mockImplementation(() => undefined);
    vi.spyOn(railwatchApi, "getUpdateState").mockResolvedValue({ phase: "idle", currentVersion: "1.0.8" });
    vi.spyOn(railwatchApi, "getAppInfo").mockResolvedValue(rosettaAppInfo({ platform: "win32" }));
    vi.spyOn(railwatchApi, "command").mockResolvedValue(undefined);

    render(<RailWatchApp />);

    await waitFor(() => expect(railwatchApi.getAppInfo).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(document.body.textContent).not.toContain("当前运行的是 Intel (x64) 版本");
  });
});
