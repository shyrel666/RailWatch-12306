// @vitest-environment jsdom
import type { ReactNode } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { RailWatchApp } from "./App";
import type { BridgeEvent, RailWatchConfig, TripDraft } from "./types";
import { createRailWatchStore, defaultConfig, defaultRuntimeInfo, railwatchStore } from "./store/railwatchStore";

vi.mock("./components/Shell", () => ({ ShellLayout: ({ children }: { children: ReactNode }) => children }));
vi.mock("./components/TripSetupPage", () => ({
  TripSetupPage: ({ runCommand }: { runCommand: (name: string, payload: Record<string, unknown>) => Promise<unknown> }) => (
    <button onClick={() => void runCommand("saveConfig", { config: railwatchStore.getState().config })}>保存行程</button>
  ),
}));

const savedConfig: RailWatchConfig = { ...defaultConfig, from_station_cn: "北京南", to_station_cn: "上海虹桥" };
let failTripLoads = 0;
let staleDraftWrites = 0;
let saveDraft: ((payload: Record<string, unknown>) => Promise<TripDraft>) | null = null;
let saveConfigRequest: Promise<unknown> | null = null;
let emit: (event: BridgeEvent) => void = () => undefined;
const command = vi.fn(async (name: string, payload: Record<string, unknown> = {}) => {
  if (name === "getRuntimeInfo") return defaultRuntimeInfo;
  if (name === "saveConfig") return saveConfigRequest ?? {};
  if (name === "saveTripDraft") {
    if (saveDraft) return saveDraft(payload);
    if (staleDraftWrites > 0) {
      staleDraftWrites -= 1;
      throw new Error("Error invoking remote method 'railwatch:command': Error: 草稿修订号已过期（当前为 80），请重新加载最新草稿。");
    }
    return { schema_version: 1, revision: payload.revision, saved_at: 2, config: payload.config };
  }
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
const draftRevisions = () => command.mock.calls.filter(([name]) => name === "saveTripDraft")
  .map(([, payload]) => payload?.revision);

beforeEach(() => {
  vi.clearAllMocks();
  failTripLoads = 0;
  staleDraftWrites = 0;
  saveDraft = null;
  saveConfigRequest = null;
  const initial = createRailWatchStore().getState();
  railwatchStore.setState({ config: initial.config, status: initial.status, runtime: initial.runtime,
    rehearsal: initial.rehearsal, rehearsalEnabled: false, activePage: "系统设置", pageSection: null,
    tripInitialized: false, editRevision: 0, draftRevision: 0, draftSaveState: "idle", savedConfig: null });
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

test("a remounted app allocates draft revisions above the revision already on disk", async () => {
  railwatchStore.setState({ tripInitialized: true, savedConfig, config: savedConfig, draftRevision: 60 });
  render(<RailWatchApp />);
  act(() => railwatchStore.getState().setConfig({ train_code: "G19" }));

  await waitFor(() => expect(draftRevisions()).toEqual([61]));
  expect(tripLoads()).toBe(0);
  await waitFor(() => expect(railwatchStore.getState().draftSaveState).toBe("saved"));
});

test("a stale draft revision moves past the runtime revision and retries once", async () => {
  staleDraftWrites = 1;
  railwatchStore.setState({ tripInitialized: true, savedConfig, config: savedConfig, draftRevision: 0 });
  render(<RailWatchApp />);
  act(() => railwatchStore.getState().setConfig({ train_code: "G19" }));

  await waitFor(() => expect(draftRevisions()).toEqual([1, 81]));
  await waitFor(() => expect(railwatchStore.getState().draftSaveState).toBe("saved"));
  expect(railwatchStore.getState().draftError).toBeNull();
  expect(railwatchStore.getState().draftRevision).toBe(81);
});

function holdFirstDraftWrite() {
  let rejectFirst!: (error: Error) => void;
  const first = new Promise<TripDraft>((_, reject) => { rejectFirst = reject; });
  let pending = true;
  saveDraft = async payload => {
    if (pending) { pending = false; return first; }
    return { schema_version: 1, revision: payload.revision as number, saved_at: 2,
      config: payload.config as RailWatchConfig };
  };
  return () => rejectFirst(new Error("草稿修订号已过期（当前为 80），请重新加载最新草稿。"));
}

test("a conflict retries the latest edit and preserves it for exit before the next autosave", async () => {
  const rejectFirst = holdFirstDraftWrite();
  railwatchStore.setState({ tripInitialized: true, savedConfig, config: savedConfig });
  const app = render(<RailWatchApp />);
  act(() => railwatchStore.getState().setConfig({ train_code: "G19" }));
  await waitFor(() => expect(draftRevisions()).toEqual([1]));
  act(() => railwatchStore.getState().setConfig({ train_code: "G23" }));
  await act(async () => { rejectFirst(); });
  app.unmount(); // The main process must be able to flush the newest staged draft now.

  expect(vi.mocked(window.railwatch!.stageDraft).mock.calls.at(-1)?.[0]).toMatchObject({
    revision: 81, config: { train_code: "G23" },
  });
  expect(command.mock.calls.filter(([name]) => name === "saveTripDraft")
    .map(([, payload]) => (payload?.config as RailWatchConfig).train_code)).toEqual(["G19", "G23"]);
  expect(railwatchStore.getState().draftSaveState).toBe("saved");
});

test("queued older snapshots cannot overwrite the latest conflict retry", async () => {
  const rejectFirst = holdFirstDraftWrite();
  railwatchStore.setState({ tripInitialized: true, savedConfig, config: savedConfig });
  render(<RailWatchApp />);
  act(() => railwatchStore.getState().setConfig({ train_code: "G19" }));
  await waitFor(() => expect(draftRevisions()).toEqual([1]));
  act(() => railwatchStore.getState().setConfig({ train_code: "G23" }));
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 700)); });
  act(() => railwatchStore.getState().setConfig({ train_code: "G25" }));
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 700)); });
  await act(async () => { rejectFirst(); });

  expect(command.mock.calls.filter(([name]) => name === "saveTripDraft")
    .map(([, payload]) => (payload?.config as RailWatchConfig).train_code)).toEqual(["G19", "G25"]);
  expect(vi.mocked(window.railwatch!.stageDraft).mock.calls.at(-1)?.[0]).toMatchObject({
    revision: 81, config: { train_code: "G25" },
  });
  expect(railwatchStore.getState().draftSaveState).toBe("saved");
});

test("edits made during a formal config save remain the latest draft", async () => {
  let finishSave!: (value: unknown) => void;
  saveConfigRequest = new Promise(resolve => { finishSave = resolve; });
  railwatchStore.setState({ tripInitialized: true, savedConfig, config: savedConfig, activePage: "行程设置" });
  render(<RailWatchApp />);
  act(() => railwatchStore.getState().setConfig({ train_code: "G19" }));
  fireEvent.click(screen.getByRole("button", { name: "保存行程" }));
  expect(command).toHaveBeenCalledWith("saveConfig", { config: expect.objectContaining({ train_code: "G19" }) });
  act(() => railwatchStore.getState().setConfig({ train_code: "G23" }));
  await act(async () => { finishSave({ saved: true }); });

  await waitFor(() => expect(railwatchStore.getState().draftSaveState).toBe("saved"));
  const writes = command.mock.calls.filter(([name]) => name === "saveTripDraft");
  expect(writes.length).toBeGreaterThan(0);
  expect(writes.every(([, payload]) => (payload?.config as RailWatchConfig).train_code === "G23")).toBe(true);
  expect(railwatchStore.getState().savedConfig?.train_code).toBe("G19");
  expect(railwatchStore.getState().config.train_code).toBe("G23");
  expect(vi.mocked(window.railwatch!.stageDraft).mock.calls.at(-1)?.[0]).toMatchObject({ config: { train_code: "G23" } });
});
