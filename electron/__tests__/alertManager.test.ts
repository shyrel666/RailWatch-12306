import { afterEach, expect, test, vi } from "vitest";

const constructed = vi.hoisted(() => ({ notifications: 0, soundWindows: 0 }));
vi.mock("electron", () => ({
  BrowserWindow: class {
    webContents = { executeJavaScript: vi.fn(async () => undefined) };
    constructor() { constructed.soundWindows += 1; }
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

import { cleanupUrgentAlert, showUrgentAlert } from "../alertManager";

afterEach(() => {
  cleanupUrgentAlert();
  constructed.notifications = 0;
  constructed.soundWindows = 0;
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
