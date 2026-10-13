import { afterEach, expect, test, vi } from "vitest";

const constructed = vi.hoisted(() => ({
  notifications: 0, soundWindows: 0, calls: [] as string[],
  finishLoad: null as (() => void) | null,
  scripts: [] as string[], duration: 220,
}));
vi.mock("electron", () => ({
  BrowserWindow: class {
    // Electron queues scripts until a load finishes, so record order rather than resolving freely.
    webContents = { executeJavaScript: vi.fn(async (script: string) => {
      constructed.calls.push("script"); constructed.scripts.push(script); return constructed.duration;
    }) };
    constructor() { constructed.soundWindows += 1; }
    loadURL(url: string) {
      constructed.calls.push(`load:${url}`);
      return new Promise<void>(resolve => { constructed.finishLoad = resolve; });
    }
    isDestroyed() { return false; }
    destroy() { return undefined; }
  },
  Notification: class {
    static isSupported() { return true; }
    constructor() { constructed.notifications += 1; }
    on() { return undefined; }
    show() { return undefined; }
  },
  ipcMain: { on: vi.fn() },
  shell: { openExternal: vi.fn() },
}));

import { cleanupUrgentAlert, previewAlertSound, showUrgentAlert, stopAlertSoundPreview,
  stopUrgentAlertLoop, updateUrgentAlertSound } from "../alertManager";
import * as soundFiles from "../alertSoundFiles";

afterEach(() => {
  cleanupUrgentAlert();
  constructed.notifications = 0;
  constructed.soundWindows = 0;
  constructed.calls = [];
  constructed.finishLoad = null;
  constructed.scripts = [];
  constructed.duration = 220;
  vi.useRealTimers();
  vi.restoreAllMocks();
});

test("the sound window loads a page before any tone script runs", async () => {
  showUrgentAlert(null, { title: "测试", message: "测试" }, {
    desktop_urgent: false, sound_loop: true, window_attention: false,
  });
  await Promise.resolve();
  expect(constructed.calls).toEqual(["load:about:blank"]);
  constructed.finishLoad?.();
  await vi.waitFor(() => expect(constructed.calls).toEqual(["load:about:blank", "script"]));
});

test("desktop notifications can be off while the alert sound remains on", () => {
  showUrgentAlert(null, { title: "测试", message: "测试" }, {
    desktop_urgent: false, sound_loop: true, window_attention: false,
  });
  expect(constructed.notifications).toBe(0);
  expect(constructed.soundWindows).toBe(1);
});

test("disabling sound stops the existing loop without creating another sound window", () => {
  showUrgentAlert(null, { title: "测试", message: "测试" }, {
    desktop_urgent: false, sound_loop: true, window_attention: false,
  });
  showUrgentAlert(null, { title: "测试", message: "测试" }, {
    desktop_urgent: true, sound_loop: false, window_attention: false,
  });
  expect(constructed.notifications).toBe(1);
  expect(constructed.soundWindows).toBe(1);
});

test("stopping before a pending page load prevents a late alert from playing", async () => {
  showUrgentAlert(null, { title: "测试", message: "测试" }, {
    desktop_urgent: false, sound_loop: true, window_attention: false,
  });
  const finishLoad = constructed.finishLoad;
  stopUrgentAlertLoop();
  finishLoad?.();
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
  expect(constructed.scripts).toHaveLength(0);
});

test("an active loop changes to the saved tone and has only one scheduled repeat", async () => {
  vi.useFakeTimers();
  showUrgentAlert(null, { title: "测试", message: "测试" }, {
    desktop_urgent: false, sound_loop: true, window_attention: false, sound_tone: "chime",
  });
  constructed.finishLoad?.();
  await vi.waitFor(() => expect(constructed.scripts).toHaveLength(1));
  expect(constructed.scripts[0]).toContain('"tone":"chime"');
  updateUrgentAlertSound({ sound_tone: "alarm" });
  constructed.finishLoad?.();
  await vi.waitFor(() => expect(constructed.scripts).toHaveLength(2));
  expect(constructed.scripts[1]).toContain('"tone":"alarm"');
  await vi.advanceTimersByTimeAsync(1800);
  expect(constructed.scripts).toHaveLength(3);
  stopUrgentAlertLoop();
  await vi.advanceTimersByTimeAsync(4000);
  expect(constructed.scripts).toHaveLength(3);
});

test("clips finish before repeating and stopping a preview leaves the urgent loop running", async () => {
  vi.useFakeTimers();
  constructed.duration = 3000;
  showUrgentAlert(null, { title: "测试", message: "测试" }, {
    desktop_urgent: false, sound_loop: true, window_attention: false,
  });
  constructed.finishLoad?.();
  await vi.waitFor(() => expect(constructed.scripts).toHaveLength(1));
  const preview = previewAlertSound({ sound_tone: "double" });
  await Promise.resolve();
  constructed.finishLoad?.();
  await expect(preview).resolves.toEqual({ duration_ms: 3000 });
  stopAlertSoundPreview();
  await vi.advanceTimersByTimeAsync(1800);
  expect(constructed.scripts).toHaveLength(2);
  await vi.advanceTimersByTimeAsync(1600);
  expect(constructed.scripts).toHaveLength(3);
  expect(constructed.notifications).toBe(0);
});

test("preview rejects unknown tones and arbitrary local paths", async () => {
  await expect(previewAlertSound({ sound_tone: "other" })).rejects.toThrow("选择无效");
  await expect(previewAlertSound({ sound_tone: "custom", sound_custom_file: "../../private.wav" })).rejects.toThrow("先导入");
  expect(constructed.soundWindows).toBe(0);
});

test("an urgent alert falls back to the original beep if its imported clip is missing", async () => {
  vi.spyOn(soundFiles, "readImportedSound").mockRejectedValue(new Error("音频文件已丢失"));
  showUrgentAlert(null, { title: "测试", message: "测试" }, {
    desktop_urgent: false, sound_loop: true, window_attention: false,
    sound_tone: "custom", sound_custom_file: "a".repeat(64) + ".wav",
  });
  constructed.finishLoad?.();
  await vi.waitFor(() => expect(constructed.scripts).toHaveLength(1));
  expect(constructed.scripts[0]).toContain('"tone":"beep"');
});
