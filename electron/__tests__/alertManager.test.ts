import type { BrowserWindow } from "electron";
import { afterEach, expect, test, vi } from "vitest";

const constructed = vi.hoisted(() => ({
  notifications: 0, soundWindows: 0, calls: [] as string[],
  finishLoad: null as (() => void) | null,
  scripts: [] as string[], duration: 220,
  notificationOptions: [] as Record<string, unknown>[], closedNotifications: 0, dockBadges: [] as string[],
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
    constructor(options: Record<string, unknown>) {
      constructed.notifications += 1;
      constructed.notificationOptions.push(options);
    }
    on() { return undefined; }
    show() { return undefined; }
    close() { constructed.closedNotifications += 1; }
  },
  app: { dock: { bounce: vi.fn(), setBadge: (text: string) => { constructed.dockBadges.push(text); } } },
  nativeImage: { createFromBitmap: (buffer: Buffer, options: object) => ({ buffer, options }) },
  ipcMain: { on: vi.fn() },
  shell: { openExternal: vi.fn() },
}));

import { alertOverlayBitmap, cleanupUrgentAlert, previewAlertSound, showNoticeAlert, showUrgentAlert, stopAlertSoundPreview,
  stopUrgentAlert, stopUrgentAlertLoop, updateUrgentAlertSound } from "../alertManager";
import * as soundFiles from "../alertSoundFiles";

afterEach(() => {
  cleanupUrgentAlert();
  constructed.notifications = 0;
  constructed.soundWindows = 0;
  constructed.calls = [];
  constructed.finishLoad = null;
  constructed.scripts = [];
  constructed.duration = 220;
  constructed.notificationOptions = [];
  constructed.closedNotifications = 0;
  constructed.dockBadges = [];
  vi.useRealTimers();
  vi.restoreAllMocks();
});

/** A main window that records what the alert does to it; `focus()` plays the user returning to it. */
function fakeWindow() {
  const listeners = new Map<string, () => void>();
  const raw = {
    isDestroyed: () => false, isMinimized: () => false, restore: vi.fn(), show: vi.fn(), focus: vi.fn(),
    flashFrame: vi.fn(), setAlwaysOnTop: vi.fn(), setOverlayIcon: vi.fn(),
    on: (name: string, listener: () => void) => { listeners.set(name, listener); },
  };
  return { window: raw as unknown as BrowserWindow, raw, focus: () => listeners.get("focus")?.() };
}
const payment = { title: "待支付", message: "请在官方页面完成支付" };
const notificationOnly = { desktop_urgent: true, sound_loop: false, window_attention: false };

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

test("a notice shows only a system notification, and none when desktop notifications are off", () => {
  const preferences = { desktop_urgent: true, sound_loop: true, window_attention: true };
  showNoticeAlert(null, { title: "起售提醒", message: "15:00 起售" }, preferences);
  expect(constructed.notifications).toBe(1);
  expect(constructed.soundWindows).toBe(0);
  showNoticeAlert(null, { title: "起售提醒", message: "15:00 起售" }, { ...preferences, desktop_urgent: false });
  expect(constructed.notifications).toBe(1);
});

test("an urgent notification stays on screen on Windows while a notice keeps the default timeout", () => {
  showUrgentAlert(null, payment, notificationOnly, "win32");
  showNoticeAlert(null, { title: "起售提醒", message: "15:00 起售" }, notificationOnly);
  expect(constructed.notificationOptions).toEqual([
    expect.objectContaining({ title: "待支付", timeoutType: "never", urgency: "critical", silent: false }),
    expect.objectContaining({ title: "起售提醒", timeoutType: "default", urgency: "normal", silent: false }),
  ]);
});

test("Windows marks the taskbar icon until the alert is stopped, then withdraws the mark and the toast", () => {
  const { window, raw } = fakeWindow();
  showUrgentAlert(window, payment, notificationOnly, "win32");
  expect(raw.setOverlayIcon).toHaveBeenCalledTimes(1);
  const [icon, description] = raw.setOverlayIcon.mock.calls[0] as [{ options: object }, string];
  expect(icon.options).toEqual({ width: 32, height: 32 });
  expect(description).toBe("有待处理的紧急提醒");
  expect(constructed.dockBadges).toEqual([]);
  stopUrgentAlert();
  expect(raw.setOverlayIcon).toHaveBeenLastCalledWith(null, "");
  expect(constructed.closedNotifications).toBe(1);
});

test("macOS badges the Dock icon instead and clears it when the alert is stopped", () => {
  const { window, raw } = fakeWindow();
  showUrgentAlert(window, payment, notificationOnly, "darwin");
  expect(constructed.dockBadges).toEqual(["!"]);
  expect(raw.setOverlayIcon).not.toHaveBeenCalled();
  stopUrgentAlert();
  expect(constructed.dockBadges).toEqual(["!", ""]);
});

test("returning to the window acknowledges the alert, but the focus the alert itself causes does not", () => {
  vi.useFakeTimers();
  const { window, raw, focus } = fakeWindow();
  showUrgentAlert(window, payment, { ...notificationOnly, window_attention: true }, "win32");
  focus();
  expect(raw.setOverlayIcon).toHaveBeenCalledTimes(1);
  expect(constructed.closedNotifications).toBe(0);
  vi.advanceTimersByTime(1600);
  focus();
  expect(raw.setOverlayIcon).toHaveBeenLastCalledWith(null, "");
  expect(constructed.closedNotifications).toBe(1);
  // Nothing is left to acknowledge, so a later focus does nothing more.
  focus();
  expect(raw.setOverlayIcon).toHaveBeenCalledTimes(2);
});

test("a newer urgent alert replaces the previous toast instead of stacking another", () => {
  showUrgentAlert(null, payment, notificationOnly, "win32");
  showUrgentAlert(null, { title: "需要核验", message: "请在受控浏览器中完成核验" }, notificationOnly, "win32");
  expect(constructed.notifications).toBe(2);
  expect(constructed.closedNotifications).toBe(1);
});

test("with desktop notifications off there is no toast, taskbar mark or Dock badge", () => {
  const { window, raw } = fakeWindow();
  const off = { desktop_urgent: false, sound_loop: false, window_attention: false };
  showUrgentAlert(window, payment, off, "win32");
  showUrgentAlert(window, payment, off, "darwin");
  expect(constructed.notifications).toBe(0);
  expect(raw.setOverlayIcon).not.toHaveBeenCalled();
  expect(constructed.dockBadges).toEqual([]);
});

test("the taskbar overlay is a red disc with a white exclamation mark on a transparent corner", () => {
  const pixels = alertOverlayBitmap();
  const at = (x: number, y: number) => [...pixels.subarray((y * 32 + x) * 4, (y * 32 + x) * 4 + 4)];
  expect(pixels).toHaveLength(32 * 32 * 4);
  expect(at(0, 0)).toEqual([0, 0, 0, 0]);
  // Windows bitmaps are BGRA.
  expect(at(6, 16)).toEqual([53, 57, 229, 255]);
  expect(at(15, 12)).toEqual([255, 255, 255, 255]);
  expect(at(15, 21)).toEqual([53, 57, 229, 255]);
  expect(at(15, 23)).toEqual([255, 255, 255, 255]);
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
