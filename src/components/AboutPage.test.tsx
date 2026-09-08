// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App as AntApp } from "antd";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { railwatchApi } from "../lib/railwatchApi";
import { defaultRuntimeInfo, defaultStatus, railwatchStore } from "../store/railwatchStore";
import { AboutPage } from "./AboutPage";

const REPO_URL = "https://github.com/shyrel666/RailWatch-12306";

function renderPage() {
  return render(
    <AntApp>
      <AboutPage />
    </AntApp>,
  );
}

function resetStore() {
  railwatchStore.setState({
    runtime: {
      ...defaultRuntimeInfo,
      app_display_name: "RailWatch 12306",
      app_version: "0.3.2",
      chrome_version: "Chrome 152",
      data_dir: "C:/RailWatch/data",
      state: { ...defaultStatus },
    },
    status: { ...defaultStatus },
  });
}

describe("AboutPage", () => {
  beforeEach(() => {
    resetStore();
    vi.restoreAllMocks();
  });

  afterEach(cleanup);

  test("shows the brand, version and environment", async () => {
    vi.spyOn(railwatchApi, "getAppInfo").mockResolvedValue({
      appVersion: "0.3.2",
      electronVersion: "39.8.10",
      chromeVersion: "142.0.7444.265",
      nodeVersion: "22.22.1",
      platform: "win32",
      arch: "x64",
    });

    renderPage();

    expect(screen.getByRole("img", { name: "RailWatch 12306" })).toBeTruthy();
    expect(screen.getByText("v0.3.2")).toBeTruthy();
    expect(screen.getByText("把行程准备、起售监控与订单跟踪，放在一个桌面工作台。")).toBeTruthy();
    expect(screen.getByRole("button", { name: /检查更新/ })).toBeTruthy();
    expect(screen.getByText(/不是 12306 官方产品/)).toBeTruthy();

    await waitFor(() =>
      expect(screen.getByText("Electron 39.8.10 · Chromium 142.0.7444.265 · Node.js 22.22.1")).toBeTruthy(),
    );
  });

  test("opens project links through the bridge", async () => {
    vi.spyOn(railwatchApi, "getAppInfo").mockRejectedValue(new Error("no bridge"));
    const openExternal = vi.spyOn(railwatchApi, "openExternal").mockResolvedValue({ ok: true });
    const user = userEvent.setup();

    renderPage();

    await user.click(screen.getByRole("button", { name: /发布与下载/ }));

    expect(openExternal).toHaveBeenCalledWith(`${REPO_URL}/releases`);
  });

  test("reports a blocked link instead of failing silently", async () => {
    vi.spyOn(railwatchApi, "getAppInfo").mockRejectedValue(new Error("no bridge"));
    vi.spyOn(railwatchApi, "openExternal").mockResolvedValue({ ok: false, error: "blocked" });
    const user = userEvent.setup();

    renderPage();

    await user.click(screen.getByRole("button", { name: /问题反馈/ }));

    expect(await screen.findByText("无法打开链接，请在浏览器中手动访问。")).toBeTruthy();
  });
});
