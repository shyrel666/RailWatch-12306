// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConfigProvider } from "antd";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { railwatchApi } from "../lib/railwatchApi";
import { defaultRuntimeInfo, defaultStatus } from "../store/railwatchStore";
import type { UpdateRuntimeState } from "../types";
import { ShellLayout } from "./Shell";

function renderShell() {
  return render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <ShellLayout
        activePage="购票监控"
        darkMode
        eventPanel={null}
        eventPanelVisible={false}
        runtime={{ ...defaultRuntimeInfo, app_version: "0.1.0" }}
        status={{ ...defaultStatus, summary: "就绪" }}
        onPageChange={vi.fn()}
        onExportLog={vi.fn()}
        onToggleEventPanel={vi.fn()}
      >
        <div>内容</div>
      </ShellLayout>
    </ConfigProvider>,
  );
}

function mockState(state: UpdateRuntimeState) {
  vi.spyOn(railwatchApi, "getUpdateState").mockResolvedValue(state);
}

const downloadedState: UpdateRuntimeState = {
  phase: "downloaded", currentVersion: "0.1.0", latestVersion: "1.2.0", downloadPercent: 100,
};

beforeEach(() => {
  vi.restoreAllMocks();
  mockState({ phase: "idle", currentVersion: "0.1.0" });
  vi.spyOn(railwatchApi, "onUpdateState").mockReturnValue(() => undefined);
});

afterEach(cleanup);

describe("ShellLayout update control", () => {
  test("renders a downward update icon in the status bar and appearance in the header", () => {
    renderShell();

    const trigger = screen.getByRole("button", { name: "检查更新" });
    expect(trigger.querySelector("svg.lucide-circle-arrow-down")).toBeTruthy();
    expect(trigger.querySelector("svg.lucide-circle-arrow-up")).toBeNull();
    expect(trigger.querySelector(".update-status-ring")).toBeNull();
    expect(screen.getByRole("radiogroup", { name: "外观主题" })).toBeTruthy();
  });

  test("shows GitHub release notes as text and the transfer figures of a running download", async () => {
    const user = userEvent.setup();
    mockState({
      phase: "downloading", currentVersion: "0.1.0", latestVersion: "1.2.0", downloadPercent: 42.4,
      downloadTransferred: 41_590_000, downloadTotal: 98_100_000, downloadSpeed: 2_300_000,
      releaseNotes: "<h1>RailWatch 12306 v1.2.0</h1>\n<h2>修复</h2>\n<ul>\n<li>修复<strong>候补</strong>入口识别。</li>\n</ul>",
    });
    renderShell();

    const trigger = await screen.findByRole("button", { name: "查看更新进度" });
    expect(trigger.querySelector(".update-status-ring")).toBeTruthy();
    await user.click(trigger);
    const dialog = await screen.findByRole("dialog", { name: "软件更新" });
    const notes = within(dialog).getByRole("region", { name: "本次更新说明" });
    expect(within(notes).getByRole("heading", { name: "修复" })).toBeTruthy();
    expect(within(notes).getByRole("listitem").textContent).toBe("修复候补入口识别。");
    expect(notes.textContent).not.toMatch(/<|RailWatch 12306 v1\.2\.0/);
    const facts = within(dialog).getByLabelText("下载详情");
    expect(facts.textContent).toContain("39.7 / 93.6 MB");
    expect(facts.textContent).toContain("2.2 MB/s");
  });

  test("opens the update panel and checks from the bottom status bar", async () => {
    const user = userEvent.setup();
    vi.spyOn(railwatchApi, "checkUpdate").mockResolvedValue({
      ok: true, currentVersion: "0.1.0", latestVersion: "0.1.0", hasUpdate: false,
      releaseName: "RailWatch 0.1.0", releaseNotes: "", publishedAt: "2026-06-01T00:00:00Z",
      releaseUrl: "", assets: [], source: "updater",
    });
    renderShell();

    const trigger = screen.getByRole("button", { name: "检查更新" });
    await user.click(trigger);
    const dialog = await screen.findByRole("dialog", { name: "软件更新" });
    expect(railwatchApi.checkUpdate).toHaveBeenCalledOnce();
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    expect(within(dialog).getByText("已是最新版本")).toBeTruthy();

    await user.click(within(dialog).getByRole("button", { name: "完成" }));
    await user.click(trigger);
    await screen.findByRole("dialog", { name: "软件更新" });
    expect(railwatchApi.checkUpdate).toHaveBeenCalledTimes(2);
  });

  test.each([42.4, undefined])("keeps a download running when opening and closing the panel (progress %s)", async (downloadPercent) => {
    const user = userEvent.setup();
    mockState({ phase: "downloading", currentVersion: "0.1.0", latestVersion: "1.2.0", downloadPercent });
    const checkUpdate = vi.spyOn(railwatchApi, "checkUpdate");
    const installUpdate = vi.spyOn(railwatchApi, "installUpdate");
    renderShell();

    const trigger = await screen.findByRole("button", { name: "查看更新进度" });
    await user.click(trigger);
    const dialog = await screen.findByRole("dialog", { name: "软件更新" });
    const progress = within(dialog).getByRole("progressbar", { name: "更新下载进度" });
    expect(progress.getAttribute("aria-valuenow")).toBe(downloadPercent === undefined ? null : "42");
    expect(progress.getAttribute("aria-valuetext")).toBe(downloadPercent === undefined ? "正在下载更新" : "42%");
    expect(within(dialog).queryByRole("button", { name: /安装|暂停|取消/ })).toBeNull();

    await user.click(within(dialog).getByRole("button", { name: "收起" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "软件更新" })).toBeNull());
    expect(document.activeElement).toBe(trigger);
    expect(trigger.getAttribute("aria-expanded")).toBe("false");

    await user.click(trigger);
    const reopened = await screen.findByRole("dialog", { name: "软件更新" });
    expect(within(reopened).getByRole("progressbar").getAttribute("aria-valuenow"))
      .toBe(downloadPercent === undefined ? null : "42");
    const closeButton = within(reopened).getByRole("button", { name: "收起更新面板" });
    closeButton.focus();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "软件更新" })).toBeNull());
    expect(document.activeElement).toBe(trigger);
    expect(checkUpdate).not.toHaveBeenCalled();
    expect(installUpdate).not.toHaveBeenCalled();
  });

  test("does not check again while Windows is preparing an automatic download", async () => {
    const user = userEvent.setup();
    mockState({ phase: "available", currentVersion: "0.1.0", latestVersion: "1.2.0", installMode: "auto" });
    const checkUpdate = vi.spyOn(railwatchApi, "checkUpdate");
    renderShell();

    const trigger = await screen.findByRole("button", { name: "查看可用更新" });
    await user.click(trigger);
    const dialog = await screen.findByRole("dialog", { name: "软件更新" });
    expect(within(dialog).getByText("正在准备下载更新，请稍候。")).toBeTruthy();
    expect(within(dialog).getByRole("progressbar").getAttribute("aria-valuenow")).toBeNull();
    expect(within(dialog).queryByRole("button", { name: "检查更新" })).toBeNull();
    await user.click(within(dialog).getByRole("button", { name: "收起" }));
    await user.click(trigger);
    expect(checkUpdate).not.toHaveBeenCalled();
  });

  test("installs only from the explicit downloaded-update panel button", async () => {
    const user = userEvent.setup();
    mockState(downloadedState);
    const installUpdate = vi.spyOn(railwatchApi, "installUpdate").mockResolvedValue({ ok: true });
    renderShell();

    await user.click(await screen.findByRole("button", { name: "查看已下载更新" }));
    const dialog = await screen.findByRole("dialog", { name: "软件更新" });
    expect(installUpdate).not.toHaveBeenCalled();
    expect(within(dialog).getByRole("progressbar").getAttribute("aria-valuenow")).toBe("100");
    await user.click(within(dialog).getByRole("button", { name: "立即重启安装" }));
    expect(installUpdate).toHaveBeenCalledOnce();
  });

  test("shows the actual installation-block reason and keeps the downloaded update retryable", async () => {
    const user = userEvent.setup();
    const reason = "存在未完成订单，请处理后再安装更新。";
    mockState(downloadedState);
    const installUpdate = vi.spyOn(railwatchApi, "installUpdate")
      .mockResolvedValueOnce({ ok: false, error: reason }).mockResolvedValueOnce({ ok: true });
    renderShell();

    await user.click(await screen.findByRole("button", { name: "查看已下载更新" }));
    const dialog = await screen.findByRole("dialog", { name: "软件更新" });
    await user.click(within(dialog).getByRole("button", { name: "立即重启安装" }));
    expect((await within(dialog).findByRole("alert")).textContent).toContain(reason);
    expect(within(dialog).getByText("更新已准备好")).toBeTruthy();
    expect(within(dialog).getByRole("progressbar").getAttribute("aria-valuenow")).toBe("100");
    await user.click(within(dialog).getByRole("button", { name: "立即重启安装" }));
    expect(installUpdate).toHaveBeenCalledTimes(2);
    await waitFor(() => expect(within(dialog).queryByRole("alert")).toBeNull());
  });

  test("coalesces repeated install clicks while installation preparation is pending", async () => {
    const user = userEvent.setup();
    let resolveInstall: ((result: { ok: boolean }) => void) | undefined;
    mockState(downloadedState);
    const installUpdate = vi.spyOn(railwatchApi, "installUpdate").mockImplementation(() => new Promise(resolve => {
      resolveInstall = resolve;
    }));
    renderShell();

    await user.click(await screen.findByRole("button", { name: "查看已下载更新" }));
    const dialog = await screen.findByRole("dialog", { name: "软件更新" });
    await user.dblClick(within(dialog).getByRole("button", { name: "立即重启安装" }));
    expect(installUpdate).toHaveBeenCalledOnce();
    const preparing = within(dialog).getByRole("button", { name: "准备安装中" }) as HTMLButtonElement;
    expect(preparing.disabled).toBe(true);
    resolveInstall?.({ ok: true });
    await within(dialog).findByRole("button", { name: "立即重启安装" });
  });

  test("opens the macOS release page only from the manual-update panel action", async () => {
    const user = userEvent.setup();
    const releaseUrl = "https://github.com/shyrel666/RailWatch-12306/releases/tag/v1.2.0";
    mockState({
      phase: "available", currentVersion: "0.1.0", latestVersion: "1.2.0", installMode: "manual",
      result: { ok: true, currentVersion: "0.1.0", latestVersion: "1.2.0", hasUpdate: true, releaseName: "1.2.0",
        releaseNotes: "", publishedAt: "", releaseUrl, assets: [], source: "updater" },
    });
    const openExternal = vi.spyOn(railwatchApi, "openExternal").mockResolvedValue({ ok: true });
    const installUpdate = vi.spyOn(railwatchApi, "installUpdate");
    const checkUpdate = vi.spyOn(railwatchApi, "checkUpdate");
    renderShell();

    await user.click(await screen.findByRole("button", { name: "查看可用更新" }));
    const dialog = await screen.findByRole("dialog", { name: "软件更新" });
    expect(openExternal).not.toHaveBeenCalled();
    expect(within(dialog).queryByRole("progressbar")).toBeNull();
    await user.click(within(dialog).getByRole("button", { name: "前往下载" }));
    expect(openExternal).toHaveBeenCalledExactlyOnceWith(releaseUrl);
    expect(installUpdate).not.toHaveBeenCalled();
    expect(checkUpdate).not.toHaveBeenCalled();
  });
});
