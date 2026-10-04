// @vitest-environment jsdom
import type { ReactNode } from "react";
import { act, cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { RailWatchApp } from "./App";
import type { BridgeEvent, RailWatchConfig } from "./types";
import { createRailWatchStore, defaultConfig, defaultRuntimeInfo, railwatchStore } from "./store/railwatchStore";

vi.mock("./components/Shell", () => ({ ShellLayout: ({ children }: { children: ReactNode }) => children }));
vi.mock("./components/TripSetupPage", () => ({ TripSetupPage: () => null }));

const savedConfig: RailWatchConfig = { ...defaultConfig, from_station_cn: "北京南", to_station_cn: "上海虹桥" };
let failTripLoads = 0;
let emit: (event: BridgeEvent) => void = () => undefined;
const command = vi.fn(async (name: string) => {
  if (name === "getRuntimeInfo") return defaultRuntimeInfo;
  if (name === "loadTripState") {
    if (failTripLoads > 0) {
      failTripLoads -= 1;
      throw new Error("runtime unavailable");
    }
    return { saved_config: savedConfig, saved_at: 1, draft: { status: "missing", draft: null, warning: null } };
  }
  if (name === "loadPreferences") return { theme: "light", close_to_tray: false, auto_rehearsal: false, notification_settings: {} };
  if (name === "rehearsalHistory") return { items: [] };
  return {};
});

const tripLoads = () => command.mock.calls.filter(([name]) => name === "loadTripState").length;

beforeEach(() => {
  vi.clearAllMocks();
  failTripLoads = 0;
  const initial = createRailWatchStore().getState();
  railwatchStore.setState({ config: initial.config, status: initial.status, runtime: initial.runtime,
    rehearsal: initial.rehearsal, rehearsalEnabled: false, activePage: "系统设置", pageSection: null,
    tripInitialized: false, editRevision: 0, savedConfig: null });
  window.railwatch = { command, stageDraft: vi.fn(),
    onEvent: (handler: (event: BridgeEvent) => void) => { emit = handler; return () => {}; },
    onConfirmRequest: () => () => {}, onUpdateState: () => () => {}, stopUrgentAlert: vi.fn() } as unknown as NonNullable<typeof window.railwatch>;
});
afterEach(() => { cleanup(); delete window.railwatch; });

test("a failed initial trip load is retried after the runtime restarts", async () => {
  failTripLoads = 1;
  render(<RailWatchApp />);
  await waitFor(() => expect(tripLoads()).toBe(1));
  expect(railwatchStore.getState().tripInitialized).toBe(false);

  act(() => emit({ event: "runtimeRestarted", payload: {} } as BridgeEvent));

  await waitFor(() => expect(railwatchStore.getState().tripInitialized).toBe(true));
  expect(railwatchStore.getState().savedConfig?.from_station_cn).toBe("北京南");
  expect(railwatchStore.getState().savedConfig?.to_station_cn).toBe("上海虹桥");
  expect(tripLoads()).toBe(2);
});

test("opening trip settings retries an uninitialized trip and stops once loaded", async () => {
  failTripLoads = 1;
  render(<RailWatchApp />);
  await waitFor(() => expect(tripLoads()).toBe(1));

  act(() => railwatchStore.setState({ activePage: "行程设置" }));
  await waitFor(() => expect(railwatchStore.getState().tripInitialized).toBe(true));

  act(() => railwatchStore.setState({ activePage: "系统设置" }));
  act(() => railwatchStore.setState({ activePage: "行程设置" }));
  act(() => emit({ event: "runtimeRestarted", payload: {} } as BridgeEvent));
  await waitFor(() => expect(command.mock.calls.filter(([name]) => name === "getRuntimeInfo").length).toBeGreaterThan(1));
  expect(tripLoads()).toBe(2);
});
