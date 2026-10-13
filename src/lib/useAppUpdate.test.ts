// @vitest-environment jsdom
import { createElement, type ReactNode } from "react";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { AppUpdateContext, getUpdateStatusLabel, useAppUpdate } from "./useAppUpdate";
import { railwatchApi } from "./railwatchApi";
import type { UpdateRuntimeState } from "../types";

describe("getUpdateStatusLabel", () => {
  test("describes downloaded update state", () => {
    const state: UpdateRuntimeState = {
      phase: "downloaded",
      currentVersion: "0.1.0",
      latestVersion: "1.2.0",
    };

    expect(getUpdateStatusLabel(state)).toBe("新版本 v1.2.0 已下载，等待重启安装");
  });

  test("manual mode points to the macOS release page instead of a download", () => {
    expect(getUpdateStatusLabel({ phase: "available", currentVersion: "0.6.0", latestVersion: "0.6.1", installMode: "manual" }))
      .toBe("发现新版本 v0.6.1，请前往发布页下载 macOS 安装包");
    expect(getUpdateStatusLabel({ phase: "available", currentVersion: "0.6.0", latestVersion: "0.6.1", installMode: "auto" }))
      .toBe("发现新版本 v0.6.1，正在准备下载…");
  });

  test("describes download progress", () => {
    const state: UpdateRuntimeState = {
      phase: "downloading",
      currentVersion: "0.1.0",
      latestVersion: "1.2.0",
      downloadPercent: 42.4,
    };

    expect(getUpdateStatusLabel(state)).toBe("正在下载更新 42%");
  });
});

describe("update controller", () => {
  let listeners: Set<(state: UpdateRuntimeState) => void>;
  const idle: UpdateRuntimeState = { phase: "idle", currentVersion: "0.7.0", installMode: "auto" };
  const downloaded: UpdateRuntimeState = { ...idle, phase: "downloaded", latestVersion: "0.7.1", downloadPercent: 100 };
  const available = { ok: true as const, currentVersion: "0.7.0", latestVersion: "0.7.1", hasUpdate: true, releaseName: "0.7.1", releaseNotes: "- 修复状态同步", publishedAt: "", releaseUrl: "https://github.com/shyrel666/RailWatch-12306/releases/tag/v0.7.1", assets: [], source: "updater" as const };

  beforeEach(() => {
    vi.restoreAllMocks();
    listeners = new Set();
    vi.spyOn(railwatchApi, "getUpdateState").mockResolvedValue(idle);
    vi.spyOn(railwatchApi, "onUpdateState").mockImplementation((listener) => {
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    });
  });
  afterEach(cleanup);

  test("a delayed initial snapshot cannot replace live download progress", async () => {
    let finish!: (state: UpdateRuntimeState) => void;
    vi.spyOn(railwatchApi, "getUpdateState").mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    const { result } = renderHook(() => useAppUpdate("0.7.0"));
    await act(async () => { listeners.forEach(listener => listener({ ...idle, phase: "downloading", downloadPercent: 67 })); });
    await act(async () => { finish(idle); });
    expect(result.current.updateState.phase).toBe("downloading");
    expect(result.current.updateState.downloadPercent).toBe(67);
  });

  test("a check result cannot roll back a newer downloaded event", async () => {
    let finish!: (value: typeof available) => void;
    vi.spyOn(railwatchApi, "checkUpdate").mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    const { result } = renderHook(() => useAppUpdate("0.7.0"));
    await waitFor(() => expect(railwatchApi.getUpdateState).toHaveBeenCalledOnce());
    let request!: Promise<void>;
    act(() => { request = result.current.handleCheckUpdate(); });
    await act(async () => { listeners.forEach(listener => listener(downloaded)); });
    await act(async () => { finish(available); await request; });
    expect(result.current.updateState.phase).toBe("downloaded");
    expect(result.current.isUpdating).toBe(false);
  });

  test("a delayed snapshot cannot reset a check started from the open panel", async () => {
    let snapshot!: (state: UpdateRuntimeState) => void;
    let finish!: (value: typeof available) => void;
    vi.spyOn(railwatchApi, "getUpdateState").mockImplementation(() => new Promise(resolve => { snapshot = resolve; }));
    vi.spyOn(railwatchApi, "checkUpdate").mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    const { result } = renderHook(() => useAppUpdate("0.7.0"));
    let request!: Promise<void>;
    act(() => { request = result.current.handleCheckUpdate(); });
    await act(async () => { snapshot(idle); });
    expect(result.current.updateState.phase).toBe("checking");
    await act(async () => { finish(available); await request; });
    expect(result.current.updateState.phase).toBe("available");
    expect(result.current.updateState.releaseNotes).toBe(available.releaseNotes);
  });

  test("download and automatic preparation never start another check", async () => {
    const check = vi.spyOn(railwatchApi, "checkUpdate");
    const { result } = renderHook(() => useAppUpdate("0.7.0"));
    for (const phase of ["downloading", "available"] as const) {
      await act(async () => { listeners.forEach(listener => listener({ ...idle, phase })); });
      await act(async () => { await result.current.handleCheckUpdate(); await result.current.handlePrimaryAction(); });
    }
    expect(check).not.toHaveBeenCalled();
  });

  test("shared entry points use one subscription and preserve blocked installation errors", async () => {
    vi.spyOn(railwatchApi, "getUpdateState").mockResolvedValue(downloaded);
    let finish!: (value: { ok: boolean; error?: string }) => void;
    const install = vi.spyOn(railwatchApi, "installUpdate").mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    function Wrapper({ children }: { children: ReactNode }) {
      const update = useAppUpdate("0.7.0");
      return createElement(AppUpdateContext.Provider, { value: update }, children);
    }
    const { result } = renderHook(() => ({ first: useAppUpdate("0.7.0"), second: useAppUpdate("0.7.0") }), { wrapper: Wrapper });
    await waitFor(() => expect(result.current.first.updateState.phase).toBe("downloaded"));
    expect(listeners.size).toBe(1);
    let first!: Promise<void>;
    let second!: Promise<void>;
    act(() => { first = result.current.first.handleInstallUpdate(); second = result.current.second.handleInstallUpdate(); });
    expect(install).toHaveBeenCalledOnce();
    expect(result.current.first.isInstalling).toBe(true);
    expect(result.current.second.isInstalling).toBe(true);
    await act(async () => { finish({ ok: false, error: "监控任务仍在运行，更新已推迟。" }); await Promise.all([first, second]); });
    expect(result.current.first.updateState.error).toBe("监控任务仍在运行，更新已推迟。");
    expect(result.current.second.updateState).toBe(result.current.first.updateState);
    expect(result.current.first.updateState.phase).toBe("downloaded");
    expect(result.current.second.isInstalling).toBe(false);
  });
});
