import { beforeEach, expect, test, vi } from "vitest";

const harness = vi.hoisted(() => ({
  shown: undefined as undefined | (() => void),
  send: vi.fn(), invoke: vi.fn(),
  bridge: undefined as undefined | {
    whenWindowShown: () => Promise<void>;
    finishSplash: () => void;
    openDataDir: () => Promise<unknown>;
    exportTripBundle: () => Promise<unknown>;
    importTripBundle: () => Promise<unknown>;
  },
}));

vi.mock("electron", () => ({
  ipcRenderer: {
    once: (channel: string, callback: () => void) => {
      if (channel === "railwatch:window-shown") harness.shown = callback;
    },
    send: harness.send,
    invoke: harness.invoke,
  },
  contextBridge: {
    exposeInMainWorld: (_name: string, bridge: typeof harness.bridge) => { harness.bridge = bridge; },
  },
}));

beforeEach(async () => {
  vi.resetModules();
  harness.shown = undefined;
  harness.send.mockClear();
  harness.invoke.mockReset();
  harness.bridge = undefined;
  await import("../preload");
});

test("the renderer waits until Electron reports that the window is shown", async () => {
  let ready = false;
  const waiting = harness.bridge!.whenWindowShown().then(() => { ready = true; });
  await Promise.resolve();
  expect(ready).toBe(false);

  harness.shown!();
  await waiting;
  expect(ready).toBe(true);
});

test("a show event received before the renderer loads is remembered", async () => {
  harness.shown!();

  await expect(harness.bridge!.whenWindowShown()).resolves.toBeUndefined();
  await expect(harness.bridge!.whenWindowShown()).resolves.toBeUndefined();
});

test("finishSplash notifies main process when startup splash starts dismissing", () => {
  harness.bridge!.finishSplash();
  expect(harness.send).toHaveBeenCalledWith("railwatch:splash-finished");
});

test("data directory and trip backup methods invoke dedicated IPC without renderer arguments", async () => {
  harness.invoke.mockResolvedValue({ ok: true });
  await expect(harness.bridge!.openDataDir()).resolves.toEqual({ ok: true });
  await expect(harness.bridge!.exportTripBundle()).resolves.toEqual({ ok: true });
  await expect(harness.bridge!.importTripBundle()).resolves.toEqual({ ok: true });
  expect(harness.invoke.mock.calls).toEqual([
    ["railwatch:open-data-dir"], ["railwatch:export-trip-bundle"], ["railwatch:import-trip-bundle"],
  ]);
});
