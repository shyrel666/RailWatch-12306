// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { railwatchApi } from "../lib/railwatchApi";
import { defaultRuntimeInfo, defaultStatus } from "../store/railwatchStore";
import { ShellLayout } from "./Shell";

afterEach(cleanup);

describe("ShellLayout update control", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(railwatchApi, "getUpdateState").mockResolvedValue({
      phase: "idle",
      currentVersion: "0.1.0",
    });
    vi.spyOn(railwatchApi, "onUpdateState").mockReturnValue(() => undefined);
  });

  test("renders update control to the left of theme toggle", () => {
    render(
      <ShellLayout
        activePage="购票监控"
        darkMode
        eventPanel={null}
        eventPanelVisible
        runtime={{ ...defaultRuntimeInfo, app_version: "0.1.0" }}
        status={{ ...defaultStatus, summary: "就绪" }}
        onPageChange={vi.fn()}
        onExportLog={vi.fn()}
        onThemeChange={vi.fn()}
        onToggleEventPanel={vi.fn()}
      >
        <div>内容</div>
      </ShellLayout>,
    );

    expect(screen.getByRole("button", { name: "检查更新" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "切换到明亮主题" })).toBeTruthy();
  });

  test("checks for updates from bottom status bar", async () => {
    const user = userEvent.setup();
    vi.spyOn(railwatchApi, "checkUpdate").mockResolvedValue({
      ok: true,
      currentVersion: "0.1.0",
      latestVersion: "0.1.0",
      hasUpdate: false,
      releaseName: "RailWatch 0.1.0",
      releaseNotes: "",
      publishedAt: "2026-06-01T00:00:00Z",
      releaseUrl: "",
      assets: [],
      source: "updater",
    });

    render(
      <ShellLayout
        activePage="购票监控"
        darkMode
        eventPanel={null}
        eventPanelVisible
        runtime={{ ...defaultRuntimeInfo, app_version: "0.1.0" }}
        status={{ ...defaultStatus, summary: "就绪" }}
        onPageChange={vi.fn()}
        onExportLog={vi.fn()}
        onThemeChange={vi.fn()}
        onToggleEventPanel={vi.fn()}
      >
        <div>内容</div>
      </ShellLayout>,
    );

    await user.click(screen.getByRole("button", { name: "检查更新" }));
    await waitFor(() => {
      expect(railwatchApi.checkUpdate).toHaveBeenCalledWith({ force: true });
    });
  });

  test("installs downloaded update from bottom status bar", async () => {
    const user = userEvent.setup();
    vi.spyOn(railwatchApi, "getUpdateState").mockResolvedValue({
      phase: "downloaded",
      currentVersion: "0.1.0",
      latestVersion: "1.2.0",
      downloadPercent: 100,
    });
    vi.spyOn(railwatchApi, "installUpdate").mockResolvedValue({ ok: true });

    render(
      <ShellLayout
        activePage="购票监控"
        darkMode
        eventPanel={null}
        eventPanelVisible
        runtime={{ ...defaultRuntimeInfo, app_version: "0.1.0" }}
        status={{ ...defaultStatus, summary: "就绪" }}
        onPageChange={vi.fn()}
        onExportLog={vi.fn()}
        onThemeChange={vi.fn()}
        onToggleEventPanel={vi.fn()}
      >
        <div>内容</div>
      </ShellLayout>,
    );

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "立即重启安装" })).toBeTruthy();
    });

    await user.click(screen.getByRole("button", { name: "立即重启安装" }));
    expect(railwatchApi.installUpdate).toHaveBeenCalledOnce();
  });
});
