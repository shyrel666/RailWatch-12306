import { BrowserWindow, Notification, app, ipcMain, nativeImage, shell, type NativeImage } from "electron";
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
// True from an urgent alert until the user acknowledges it or it is stopped.
let urgentAlertPending = false;
// Kept so the toast can be withdrawn once acknowledged, and so its click handler stays alive.
let urgentNotification: Notification | null = null;
let overlayWindow: BrowserWindow | null = null;
let overlayIcon: NativeImage | null = null;
let dockBadgeShown = false;
const FOCUS_GRACE_MS = 1500;
const ALWAYS_ON_TOP_MS = 15000;
const OVERLAY_SIZE = 32;
const OVERLAY_DESCRIPTION = "有待处理的紧急提醒";
const DOCK_BADGE = "!";

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

/**
 * Raw pixels of the taskbar overlay: a red disc with a white exclamation mark.
 * Windows bitmaps are BGRA with premultiplied alpha.
 */
export function alertOverlayBitmap(size: number = OVERLAY_SIZE): Buffer {
  const pixels = Buffer.alloc(size * size * 4);
  const centre = (size - 1) / 2;
  const radius = size / 2 - 1;
  const unit = size / 16; // The mark is laid out on the 16 px grid Windows shows it at.
  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      // One pixel of soft edge keeps the disc round at this size.
      const coverage = Math.min(1, Math.max(0, radius + 0.5 - Math.hypot(x - centre, y - centre)));
      if (coverage === 0) continue;
      const column = x / unit;
      const row = y / unit;
      const inMark = column >= 7 && column < 9 && ((row >= 3.5 && row < 9.5) || (row >= 11 && row < 13));
      const [red, green, blue] = inMark ? [255, 255, 255] : [229, 57, 53];
      const offset = (y * size + x) * 4;
      pixels[offset] = Math.round(blue * coverage);
      pixels[offset + 1] = Math.round(green * coverage);
      pixels[offset + 2] = Math.round(red * coverage);
      pixels[offset + 3] = Math.round(255 * coverage);
    }
  }
  return pixels;
}

/**
 * Markers on the app icon that stay until the alert is acknowledged, for when
 * the notification was missed: a taskbar overlay on Windows, a Dock badge on macOS.
 */
function showIconBadge(mainWindow: BrowserWindow | null, platform: NodeJS.Platform): void {
  if (platform === "win32") {
    if (!mainWindow || mainWindow.isDestroyed()) return;
    overlayIcon ??= nativeImage.createFromBitmap(alertOverlayBitmap(), { width: OVERLAY_SIZE, height: OVERLAY_SIZE });
    mainWindow.setOverlayIcon(overlayIcon, OVERLAY_DESCRIPTION);
    overlayWindow = mainWindow;
  } else if (platform === "darwin") {
    app.dock?.setBadge(DOCK_BADGE);
    dockBadgeShown = true;
  }
}

function clearIconBadge(): void {
  if (overlayWindow && !overlayWindow.isDestroyed()) overlayWindow.setOverlayIcon(null, "");
  overlayWindow = null;
  if (dockBadgeShown) app.dock?.setBadge("");
  dockBadgeShown = false;
}

function closeUrgentNotification(): void {
  urgentNotification?.close();
  urgentNotification = null;
}

/** Stop the looping tone, release the window's flash/always-on-top state and withdraw the icon badge and toast. */
export function stopUrgentAlert(): void {
  urgentAlertPending = false;
  stopUrgentAlertLoop();
  if (alwaysOnTopTimer) {
    clearTimeout(alwaysOnTopTimer);
    alwaysOnTopTimer = null;
  }
  if (trackedMainWindow && !trackedMainWindow.isDestroyed()) {
    trackedMainWindow.setAlwaysOnTop(false);
    trackedMainWindow.flashFrame(false);
  }
  clearIconBadge();
  closeUrgentNotification();
}

function attachFocusAutoStop(mainWindow: BrowserWindow): void {
  if (trackedMainWindow === mainWindow) {
    return;
  }
  trackedMainWindow = mainWindow;
  // 用户主动聚焦窗口即视为已知晓告警；保留宽限期以忽略告警本身触发的程序化聚焦。
  mainWindow.on("focus", () => {
    if (urgentAlertPending && Date.now() - alertShownAt > FOCUS_GRACE_MS) {
      stopUrgentAlert();
    }
  });
}

function showDesktopNotification(mainWindow: BrowserWindow | null, title: string, body: string,
  options: { urgent: boolean; silent: boolean }): Notification {
  const notification = new Notification({
    title, body, silent: options.silent,
    urgency: options.urgent ? "critical" : "normal",
    // Windows: an urgent toast stays on screen with a close button. A default
    // toast slides into the notification centre after a few seconds.
    timeoutType: options.urgent ? "never" : "default",
  });
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
  return notification;
}

/** A system notification only: no sound loop, no window raise. For reminders that need no immediate action. */
export function showNoticeAlert(mainWindow: BrowserWindow | null, payload: UrgentAlertPayload, preferences: AlertPreferences): void {
  if (preferences.desktop_urgent && Notification.isSupported()) {
    showDesktopNotification(mainWindow, payload.title || "RailWatch 提醒", payload.message || "", { urgent: false, silent: false });
  }
}

export function showUrgentAlert(mainWindow: BrowserWindow | null, payload: UrgentAlertPayload, preferences: AlertPreferences,
  platform: NodeJS.Platform = process.platform): void {
  const title = payload.title || "RailWatch 提醒";
  const body = payload.message || "";
  // A newer alert replaces the previous toast: persistent toasts would otherwise pile up.
  closeUrgentNotification();
  if (preferences.desktop_urgent) {
    if (Notification.isSupported()) {
      urgentNotification = showDesktopNotification(mainWindow, title, body, { urgent: true, silent: preferences.sound_loop });
    }
    showIconBadge(mainWindow, platform);
  } else {
    clearIconBadge();
  }
  urgentAlertPending = true;
  alertShownAt = Date.now();
  if (mainWindow && !mainWindow.isDestroyed()) attachFocusAutoStop(mainWindow);

  if (preferences.window_attention && mainWindow && !mainWindow.isDestroyed()) {
    if (mainWindow.isMinimized()) {
      mainWindow.restore();
    }
    mainWindow.show();
    mainWindow.focus();
    mainWindow.flashFrame(true);
    // flashFrame has no effect on macOS; bounce the Dock icon until focused.
    if (platform === "darwin") app.dock?.bounce("critical");
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
