import { BrowserWindow, Notification, app, ipcMain, shell } from "electron";
import { isRecord } from "./ipcSecurity";
import { isAlertSoundTone, readImportedSound, type AlertSoundSelection } from "./alertSoundFiles";
import { AlertSoundPlayer, type AlertSoundPayload } from "./alertSoundPlayer";

type UrgentAlertPayload = {
  title: string;
  message: string;
  train_code?: string;
  kind?: "notify" | "humanAction";
};

export type AlertPreferences = AlertSoundSelection & {
  desktop_urgent: boolean;
  sound_loop: boolean;
  window_attention: boolean;
};

let alertInterval: NodeJS.Timeout | null = null;
let alertLoopActive = false;
let alertGeneration = 0;
let activeSound: AlertSoundSelection = {};
const urgentPlayer = new AlertSoundPlayer();
const previewPlayer = new AlertSoundPlayer();
let previewGeneration = 0;
let previewTimer: NodeJS.Timeout | null = null;
let alwaysOnTopTimer: NodeJS.Timeout | null = null;
let trackedMainWindow: BrowserWindow | null = null;
let alertShownAt = 0;
const FOCUS_GRACE_MS = 1500;
const ALWAYS_ON_TOP_MS = 15000;

function normalizedSelection(selection: AlertSoundSelection): AlertSoundSelection {
  return {
    sound_tone: isAlertSoundTone(selection.sound_tone) ? selection.sound_tone : "beep",
    sound_custom_file: selection.sound_tone === "custom" ? selection.sound_custom_file : "",
  };
}

async function soundPayload(selection: AlertSoundSelection): Promise<AlertSoundPayload> {
  const tone = selection.sound_tone || "beep";
  return tone === "custom"
    ? { tone, audio: await readImportedSound(selection.sound_custom_file) }
    : { tone };
}

export function startUrgentAlertLoop(selection: AlertSoundSelection = {}): void {
  const next = normalizedSelection(selection);
  if (alertLoopActive && JSON.stringify(activeSound) === JSON.stringify(next)) return;
  stopUrgentAlertLoop();
  activeSound = next;
  alertLoopActive = true;
  const generation = alertGeneration;
  urgentPlayer.prepare();
  let payload: AlertSoundPayload | null = null;
  const tick = async () => {
    let duration = 220;
    try {
      payload ??= await soundPayload(next).catch(() => ({ tone: "beep" as const }));
      if (!alertLoopActive || generation !== alertGeneration) return;
      try {
        duration = await urgentPlayer.play(payload);
      } catch (error) {
        if (payload.tone !== "custom") throw error;
        if (!alertLoopActive || generation !== alertGeneration) return;
        payload = { tone: "beep" };
        duration = await urgentPlayer.play(payload);
      }
    } catch { /* Desktop/window reminders remain available if audio is unavailable. */ }
    if (alertLoopActive && generation === alertGeneration) {
      // Let an imported clip finish; long clips never overlap or get cut off.
      alertInterval = setTimeout(() => { void tick(); }, Math.max(1800, duration + 400));
    }
  };
  void tick();
}

export function updateUrgentAlertSound(selection: AlertSoundSelection): void {
  if (alertLoopActive) startUrgentAlertLoop(selection);
}

export function stopUrgentAlertLoop(): void {
  alertLoopActive = false;
  alertGeneration++;
  if (alertInterval) {
    clearTimeout(alertInterval);
    alertInterval = null;
  }
  urgentPlayer.stop();
}

export function stopAlertSoundPreview(): void {
  previewGeneration++;
  if (previewTimer) clearTimeout(previewTimer);
  previewTimer = null;
  previewPlayer.stop();
}

export async function previewAlertSound(selection: unknown): Promise<{ duration_ms: number }> {
  if (!isRecord(selection) || !isAlertSoundTone(selection.sound_tone)) {
    throw new Error("提示音选择无效。");
  }
  stopAlertSoundPreview();
  const generation = previewGeneration;
  const payload = await soundPayload({ sound_tone: selection.sound_tone,
    sound_custom_file: typeof selection.sound_custom_file === "string" ? selection.sound_custom_file : "" });
  if (generation !== previewGeneration) return { duration_ms: 0 };
  const duration = await previewPlayer.play(payload);
  if (generation === previewGeneration && duration > 0) {
    previewTimer = setTimeout(stopAlertSoundPreview, duration + 25);
  }
  return { duration_ms: duration };
}

export async function validateImportedAlertSound(audio: string): Promise<void> {
  stopAlertSoundPreview();
  try {
    const duration = await previewPlayer.play({ tone: "custom", audio }, true);
    if (!duration) throw new Error("音频导入已中断，请重试。");
  } finally {
    stopAlertSoundPreview();
  }
}

/** Stop the looping tone and release the window's flash/always-on-top state. */
export function stopUrgentAlert(): void {
  stopUrgentAlertLoop();
  if (alwaysOnTopTimer) {
    clearTimeout(alwaysOnTopTimer);
    alwaysOnTopTimer = null;
  }
  if (trackedMainWindow && !trackedMainWindow.isDestroyed()) {
    trackedMainWindow.setAlwaysOnTop(false);
    trackedMainWindow.flashFrame(false);
  }
}

function attachFocusAutoStop(mainWindow: BrowserWindow): void {
  if (trackedMainWindow === mainWindow) {
    return;
  }
  trackedMainWindow = mainWindow;
  // 用户主动聚焦窗口即视为已知晓告警；保留宽限期以忽略告警本身触发的程序化聚焦。
  mainWindow.on("focus", () => {
    if (alertLoopActive && Date.now() - alertShownAt > FOCUS_GRACE_MS) {
      stopUrgentAlert();
    }
  });
}

function showDesktopNotification(mainWindow: BrowserWindow | null, title: string, body: string,
  options: { urgency: "critical" | "normal"; silent: boolean }): void {
  const notification = new Notification({ title, body, ...options });
  notification.on("click", () => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      if (mainWindow.isMinimized()) {
        mainWindow.restore();
      }
      mainWindow.show();
      mainWindow.focus();
    }
  });
  notification.show();
}

/** A system notification only: no sound loop, no window raise. For reminders that need no immediate action. */
export function showNoticeAlert(mainWindow: BrowserWindow | null, payload: UrgentAlertPayload, preferences: AlertPreferences): void {
  if (preferences.desktop_urgent && Notification.isSupported()) {
    showDesktopNotification(mainWindow, payload.title || "RailWatch 提醒", payload.message || "", { urgency: "normal", silent: false });
  }
}

export function showUrgentAlert(mainWindow: BrowserWindow | null, payload: UrgentAlertPayload, preferences: AlertPreferences): void {
  const title = payload.title || "RailWatch 提醒";
  const body = payload.message || "";
  if (preferences.desktop_urgent && Notification.isSupported()) {
    showDesktopNotification(mainWindow, title, body, { urgency: "critical", silent: preferences.sound_loop });
  }

  if (preferences.window_attention && mainWindow && !mainWindow.isDestroyed()) {
    attachFocusAutoStop(mainWindow);
    alertShownAt = Date.now();
    if (mainWindow.isMinimized()) {
      mainWindow.restore();
    }
    mainWindow.show();
    mainWindow.focus();
    mainWindow.flashFrame(true);
    // flashFrame has no effect on macOS; bounce the Dock icon until focused.
    if (process.platform === "darwin") app.dock?.bounce("critical");
    mainWindow.setAlwaysOnTop(true, "screen-saver");
    if (alwaysOnTopTimer) {
      clearTimeout(alwaysOnTopTimer);
    }
    alwaysOnTopTimer = setTimeout(() => {
      alwaysOnTopTimer = null;
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.setAlwaysOnTop(false);
        mainWindow.flashFrame(false);
      }
    }, ALWAYS_ON_TOP_MS);
  }
  if (preferences.sound_loop) startUrgentAlertLoop(preferences);
  else stopUrgentAlertLoop();
}

export function registerAlertIpcHandlers(isTrusted: (url: string | undefined) => boolean): void {
  ipcMain.on("railwatch:stop-alert", event => {
    if (isTrusted(event.senderFrame?.url)) stopUrgentAlert();
  });
}

export function cleanupUrgentAlert(): void {
  stopUrgentAlert();
  stopAlertSoundPreview();
}

export async function openExternalUrl(url: string): Promise<void> {
  if (url) {
    await shell.openExternal(url);
  }
}
