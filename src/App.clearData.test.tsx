// @vitest-environment jsdom
import type { ReactNode } from "react";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { RailWatchApp } from "./App";
import { createRailWatchStore, defaultConfig, defaultRuntimeInfo, railwatchStore } from "./store/railwatchStore";

vi.mock("./components/Shell", () => ({ ShellLayout: ({ children }: { children: ReactNode }) => children }));

const stageDraft = vi.fn();
const clearData = vi.fn();
const command = vi.fn(async (name: string) => {
  if (name === "clearLocalData") return clearData();
  if (name === "getRuntimeInfo") return defaultRuntimeInfo;
  if (name === "loadTripState") return { saved_config: defaultConfig, saved_at: null, draft: { status: "missing", draft: null, warning: null } };
  if (name === "loadPreferences") return { theme: "light", close_to_tray: false, auto_rehearsal: false, notification_settings: {} };
  if (name === "rehearsalHistory") return { items: [] };
  return {};
});

beforeEach(() => {
  vi.clearAllMocks();
  const initial = createRailWatchStore().getState();
  railwatchStore.setState({ config: initial.config, status: initial.status, runtime: initial.runtime,
    rehearsal: initial.rehearsal, rehearsalEnabled: false, activePage: "系统设置", pageSection: null,
    tripInitialized: false, editRevision: 0, savedConfig: null });
  window.railwatch = { command, stageDraft, onEvent: () => () => {}, onConfirmRequest: () => () => {},
    onUpdateState: () => () => {}, stopUrgentAlert: vi.fn() } as unknown as NonNullable<typeof window.railwatch>;
});
afterEach(() => { cleanup(); delete window.railwatch; localStorage.clear(); });

async function openSettings() {
  render(<RailWatchApp />);
  await waitFor(() => expect(railwatchStore.getState().tripInitialized).toBe(true));
  return screen.getByRole("button", { name: "清除数据" });
}

test("successful clear drops the staged draft and asks to reload instead of retaining old UI state", async () => {
  clearData.mockResolvedValue({ cleared: true, cleanup_pending: false });
  const button = await openSettings();
  localStorage.setItem("railwatch.theme", "dark");
  await userEvent.click(button);
  expect((await screen.findAllByText("本地数据已清除")).length).toBeGreaterThan(0);
  expect(stageDraft).toHaveBeenCalledWith(null);
  expect(localStorage.getItem("railwatch.theme")).toBeNull();
  expect(screen.getByRole("button", { name: "重新加载" })).toBeTruthy();
});

test("partial disposal is presented as incomplete with its recovery location", async () => {
  clearData.mockResolvedValue({ cleared: true, cleanup_pending: true,
    warning: "旧文件仍被占用，请关闭相关程序后重试。", remaining_paths: ["C:/test/.railwatch-clearing-123"] });
  await userEvent.click(await openSettings());
  expect((await screen.findAllByText("部分旧文件尚未清除")).length).toBeGreaterThan(0);
  expect(screen.getByText(/旧文件仍被占用/).textContent).toContain("C:/test/.railwatch-clearing-123");
  expect(screen.queryByText("本地数据已清除")).toBeNull();
});

test("cancelled clear keeps drafts and a failed clear presents the actionable error", async () => {
  clearData.mockResolvedValueOnce({ cancelled: true }).mockRejectedValueOnce(new Error(
    "Error invoking remote method 'railwatch:command': Error: 文件仍被占用，尚未删除数据。"));
  const button = await openSettings();
  await userEvent.click(button);
  expect(stageDraft).not.toHaveBeenCalledWith(null);
  await userEvent.click(button);
  expect(await screen.findByText("文件仍被占用，尚未删除数据。")).toBeTruthy();
  expect(screen.queryByText(/Error invoking remote method/)).toBeNull();
  expect(stageDraft).not.toHaveBeenCalledWith(null);
});
