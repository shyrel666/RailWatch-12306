import { beforeEach, expect, test, vi } from "vitest";

const harness = vi.hoisted(() => ({
  shown: undefined as undefined | (() => void),
  bridge: undefined as undefined | { whenWindowShown: () => Promise<void> },
}));

vi.mock("electron", () => ({
  ipcRenderer: {
    once: (channel: string, callback: () => void) => {
      if (channel === "railwatch:window-shown") harness.shown = callback;
    },
  },
  contextBridge: {
    exposeInMainWorld: (_name: string, bridge: typeof harness.bridge) => { harness.bridge = bridge; },
  },
}));

beforeEach(async () => {
  vi.resetModules();
  harness.shown = undefined;
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
