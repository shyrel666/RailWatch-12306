import { BrowserWindow, Notification, app, ipcMain, shell } from "electron";

type UrgentAlertPayload = {
  title: string;
  message: string;
  train_code?: string;
  kind?: "notify" | "humanAction";
};

let alertInterval: NodeJS.Timeout | null = null;
let alertWindow: BrowserWindow | null = null;
let alwaysOnTopTimer: NodeJS.Timeout | null = null;
let trackedMainWindow: BrowserWindow | null = null;
let alertShownAt = 0;
const FOCUS_GRACE_MS = 1500;
const ALWAYS_ON_TOP_MS = 15000;

function playAlertTone(): void {
  if (!alertWindow || alertWindow.isDestroyed()) {
    alertWindow = new BrowserWindow({
      show: false,
      width: 1,
      height: 1,
      webPreferences: {
        sandbox: true,
        nodeIntegration: false,
        contextIsolation: true,
      },
    });
  }
  void alertWindow.webContents.executeJavaScript(`
    (() => {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (!AudioCtx) return;
      const ctx = new AudioCtx();
      const oscillator = ctx.createOscillator();
      const gain = ctx.createGain();
      oscillator.type = "sine";
      oscillator.frequency.value = 880;
      gain.gain.value = 0.08;
      oscillator.connect(gain);
      gain.connect(ctx.destination);
      oscillator.start();
      setTimeout(() => {
        oscillator.stop();
        ctx.close();
      }, 220);
    })();
  `);
}

export function startUrgentAlertLoop(): void {
  if (alertInterval) {
    return;
  }
  playAlertTone();
  alertInterval = setInterval(() => playAlertTone(), 1800);
}

export function stopUrgentAlertLoop(): void {
  if (alertInterval) {
    clearInterval(alertInterval);
    alertInterval = null;
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
    if (alertInterval && Date.now() - alertShownAt > FOCUS_GRACE_MS) {
      stopUrgentAlert();
    }
  });
}

export function showUrgentAlert(mainWindow: BrowserWindow | null, payload: UrgentAlertPayload): void {
  const title = payload.title || "RailWatch 提醒";
  const body = payload.message || "";
  if (Notification.isSupported()) {
    const notification = new Notification({
      title,
      body,
      urgency: "critical",
      silent: false,
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
  }

  if (mainWindow && !mainWindow.isDestroyed()) {
    attachFocusAutoStop(mainWindow);
    alertShownAt = Date.now();
    if (mainWindow.isMinimized()) {
      mainWindow.restore();
    }
    mainWindow.show();
    mainWindow.focus();
    mainWindow.flashFrame(true);
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
    mainWindow.webContents.send("railwatch:urgent-alert", payload);
  }

  startUrgentAlertLoop();
}

export function registerAlertIpcHandlers(): void {
  ipcMain.on("railwatch:stop-alert", () => stopUrgentAlert());
  app.on("before-quit", () => {
    stopUrgentAlert();
    if (alertWindow && !alertWindow.isDestroyed()) {
      alertWindow.destroy();
      alertWindow = null;
    }
  });
}

export async function openExternalUrl(url: string): Promise<void> {
  if (url) {
    await shell.openExternal(url);
  }
}
