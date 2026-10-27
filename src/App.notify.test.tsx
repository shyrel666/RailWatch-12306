// @vitest-environment jsdom
import type { ReactNode } from "react";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { RailWatchApp } from "./App";
import { createRailWatchStore, defaultConfig, defaultRuntimeInfo, railwatchStore } from "./store/railwatchStore";
import type { BridgeEvent } from "./types";

vi.mock("./components/Shell", () => ({ ShellLayout: ({ children }: { children: ReactNode }) => children }));

const stopUrgentAlert = vi.fn();
let emitBridgeEvent: ((event: BridgeEvent) => void) | null = null;
const command = vi.fn(async (name: string) => {
  if (name === "getRuntimeInfo") return defaultRuntimeInfo;
  if (name === "loadTripState") return { saved_config: defaultConfig, saved_at: null, draft: { status: "missing", draft: null, warning: null } };
  if (name === "loadPreferences") return { theme: "light", close_to_tray: false, auto_rehearsal: false, notification_settings: {} };
  if (name === "rehearsalHistory") return { items: [] };
  return {};
});

beforeEach(() => {
  vi.clearAllMocks();
  emitBridgeEvent = null;
  const initial = createRailWatchStore().getState();
  railwatchStore.setState({ config: initial.config, status: initial.status, runtime: initial.runtime,
    rehearsal: initial.rehearsal, rehearsalEnabled: false, activePage: "仪表盘", pageSection: null,
    hits: [], notifications: [], tripInitialized: false, editRevision: 0, savedConfig: null });
  window.railwatch = {
    command, stageDraft: vi.fn(),
    onEvent: (callback: (event: BridgeEvent) => void) => {
      emitBridgeEvent = callback;
      return () => { emitBridgeEvent = null; };
    },
    onConfirmRequest: () => () => {}, onUpdateState: () => () => {}, stopUrgentAlert,
  } as unknown as NonNullable<typeof window.railwatch>;
});
afterEach(() => { cleanup(); delete window.railwatch; });

function notify(title: string, priority: string) {
  act(() => emitBridgeEvent?.({ event: "notify", payload: { title, message: `${title}详情`, priority } }));
}

function closeButton(title: string) {
  return screen.getByText(title).closest(".ant-notification-notice")!.querySelector<HTMLElement>(".ant-notification-notice-close")!;
}

test("a notice opens beside an unclosed urgent alert and closing it leaves the alarm alone", async () => {
  await act(async () => { render(<RailWatchApp />); });
  notify("待支付", "urgent");
  expect(await screen.findByText("待支付")).toBeTruthy();
  notify("起售提醒", "notice");
  expect(await screen.findByText("起售提醒")).toBeTruthy();
  expect(screen.getByText("待支付")).toBeTruthy();

  fireEvent.click(closeButton("起售提醒"));
  expect(stopUrgentAlert).not.toHaveBeenCalled();
  fireEvent.click(closeButton("待支付"));
  expect(stopUrgentAlert).toHaveBeenCalledTimes(1);
});

test("a later notice replaces an earlier one", async () => {
  await act(async () => { render(<RailWatchApp />); });
  notify("12306 登录已失效", "notice");
  expect(await screen.findByText("12306 登录已失效")).toBeTruthy();
  notify("起售提醒", "notice");
  expect(await screen.findByText("起售提醒")).toBeTruthy();
  expect(screen.queryByText("12306 登录已失效")).toBeNull();
});
