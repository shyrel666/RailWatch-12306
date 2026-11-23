import { app, BrowserWindow, Menu, Tray, dialog, ipcMain, nativeTheme, powerMonitor, powerSaveBlocker, screen, session, shell } from "electron";
import { autoUpdater } from "electron-updater";
import { RailWatchNsisUpdater } from "./nsisUpdater";
import {
  clearElectronLocalData,
  configureUnifiedUserData,
  resolveUpdaterCacheDir,
  trayCloseNotice,
  trayIconFilename,
  usesTrayMenuOnly,
} from "./appDataPaths";
import { constants } from "node:fs";
import { open, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import { listExportDirectory, listExportRoots, validateLogExport } from "./exportDialog";
import {
  loadWindowState,
  normalizeThemePreference,
  resolveWindowLayout,
  saveWindowStateSync,
  themeBackgroundColor,
  type PersistedWindowState,
  type Rect,
} from "./windowState";
import { pathToFileURL } from "node:url";
import {
  consumeExportPathGrant,
  developmentRendererUrl,
  getCommandConfirmation,
  isAllowedExternalUrl,
  isExportPathAllowed,
  isRailWatchCommand,
  isRecord,
  isTrustedRailWatchUrl,
  recordExportPathGrant,
} from "./ipcSecurity";
import { cleanupUrgentAlert, previewAlertSound, registerAlertIpcHandlers, showNoticeAlert, showUrgentAlert, stopAlertSoundPreview,
  stopUrgentAlertLoop, updateUrgentAlertSound, validateImportedAlertSound, type AlertPreferences } from "./alertManager";
import { isAlertSoundTone, prepareSoundImport, storeImportedSound } from "./alertSoundFiles";
import { ConfirmationBridge, type ConfirmationRequestPayload } from "./confirmationBridge";
import { RailWatchPythonRuntimeClient, RuntimeEvent } from "./pythonRuntime";
import {
  createUpdateManager,
  shouldEnableAutoUpdate,
  type UpdateInstallMode,
  type UpdateManager,
} from "./updateManager";
import { releaseTagUrl, resolveMacDmgDownload, resolveMacTargetArch } from "./updateChecker";

let mainWindow: BrowserWindow | null = null;
let updateManager: UpdateManager | null = null;
let tray: Tray | null = null;
let quitAllowed = false;
let exitPending = false;
let installPending = false;
let trayExplained = false;
let closePending = false;
let confirmationReady = false;
let rendererCrashed = false;
const pendingDialogPresentation: ConfirmationRequestPayload[] = [];
let runtimeContinuityUnknown = false;
let lastStatus = "空闲";
let alertPreferences: AlertPreferences = { desktop_urgent: true, sound_loop: true, window_attention: true };
let maintenanceSleep = false;
let runtimePreferencesLoaded = false;
let pendingPreferencesLoad: Promise<void> | null = null;
const urgentEventIds = new Map<string, number>();

function shouldShowUrgentEvent(id: unknown): boolean {
  if (typeof id !== "string" || !id) return true;
  const now = Date.now();
  for (const [key, at] of urgentEventIds) if (now - at > 3600000) urgentEventIds.delete(key);
  if (urgentEventIds.has(id)) return false;
  if (urgentEventIds.size >= 512) urgentEventIds.delete(urgentEventIds.keys().next().value!);
  urgentEventIds.set(id, now);
  return true;
}

function applyAlertPreferences(value: unknown): void {
  if (!isRecord(value) || !isRecord(value.notification_settings)) return;
  const settings = value.notification_settings;
  alertPreferences = {
    desktop_urgent: settings.desktop_urgent !== false,
    sound_loop: settings.sound_loop !== false,
    sound_tone: isAlertSoundTone(settings.sound_tone) ? settings.sound_tone : "beep",
    sound_custom_file: typeof settings.sound_custom_file === "string" ? settings.sound_custom_file : "",
    window_attention: settings.window_attention !== false,
  };
  if (!alertPreferences.sound_loop) stopUrgentAlertLoop();
  else updateUrgentAlertSound(alertPreferences);
}
let persistedWindowState: PersistedWindowState = {};
let windowStateSaveTimer: NodeJS.Timeout | null = null;
let splashBackgroundTimer: NodeJS.Timeout | null = null;
let splashActive = true;
let nativeThemeListenerBound = false;

function clearSplashBackgroundTimer(): void {
  if (splashBackgroundTimer) {
    clearTimeout(splashBackgroundTimer);
    splashBackgroundTimer = null;
  }
}

function completeSplashTransition(): void {
  clearSplashBackgroundTimer();
  if (!splashActive) return;
  splashActive = false;
  syncNativeTheme(persistedWindowState.theme, true);
}

function getWindowStateFilePath(): string | null {
  try {
    const userData = typeof app.getPath === "function" ? app.getPath("userData") : "";
    return userData ? path.join(userData, "window-state.json") : null;
  } catch {
    return null;
  }
}

function currentThemeBackground(): "#101113" | "#f4f3ef" {
  const theme = normalizeThemePreference(persistedWindowState.theme);
  const systemDark = typeof nativeTheme?.shouldUseDarkColors === "boolean" ? nativeTheme.shouldUseDarkColors : true;
  return themeBackgroundColor(theme, systemDark);
}

function syncWindowThemeBackground(): void {
  if (!splashActive && mainWindow && !mainWindow.isDestroyed() && typeof mainWindow.setBackgroundColor === "function") {
    mainWindow.setBackgroundColor(currentThemeBackground());
  }
}

function syncNativeTheme(rawTheme: unknown, immediateTheme = true): void {
  const theme = normalizeThemePreference(rawTheme);
  if (immediateTheme) {
    splashActive = false;
    clearSplashBackgroundTimer();
  }
  if (nativeTheme && "themeSource" in nativeTheme) {
    nativeTheme.themeSource = splashActive ? "dark" : theme;
  }
  const changed = persistedWindowState.theme !== theme;
  persistedWindowState = { ...persistedWindowState, theme };
  syncWindowThemeBackground();
  if (changed) scheduleWindowStateSave();
}

function applyRuntimePreferences(payload: unknown, immediateTheme = true): void {
  if (!isRecord(payload)) return;
  maintenanceSleep = payload.maintenance_sleep === true;
  runtimePreferencesLoaded = true;
  applyAlertPreferences(payload);
  if ("theme" in payload) {
    syncNativeTheme(payload.theme, immediateTheme);
  }
}

function loadInitialRuntimePreferences(): Promise<void> {
  if (runtimePreferencesLoaded) return Promise.resolve();
  pendingPreferencesLoad ??= pythonRuntime.request("loadPreferences").then((prefs) => {
    // A preference save or reset may have supplied a newer snapshot while this read was in flight.
    if (!runtimePreferencesLoaded) applyRuntimePreferences(prefs, false);
  }).catch(() => undefined).finally(() => { pendingPreferencesLoad = null; });
  return pendingPreferencesLoad;
}

function getWorkAreaDisplays(): { displays: Rect[]; primaryWorkArea: Rect } {
  const fallback: Rect = { x: 0, y: 0, width: 1440, height: 900 };
  if (!screen || typeof screen.getPrimaryDisplay !== "function") {
    return { displays: [fallback], primaryWorkArea: fallback };
  }
  const primaryWorkArea = screen.getPrimaryDisplay()?.workArea ?? fallback;
  const allDisplays = typeof screen.getAllDisplays === "function" ? screen.getAllDisplays() : [];
  const displays = allDisplays.map((item) => item.workArea).filter(Boolean);
  return {
    displays: displays.length ? displays : [primaryWorkArea],
    primaryWorkArea,
  };
}

function captureWindowBounds(): void {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  const maximized = typeof mainWindow.isMaximized === "function" ? mainWindow.isMaximized() : false;
  const bounds =
    maximized && typeof mainWindow.getNormalBounds === "function"
      ? mainWindow.getNormalBounds()
      : typeof mainWindow.getBounds === "function"
        ? mainWindow.getBounds()
        : null;
  if (bounds && bounds.width > 0 && bounds.height > 0) {
    persistedWindowState = {
      ...persistedWindowState,
      x: Math.round(bounds.x),
      y: Math.round(bounds.y),
      width: Math.round(bounds.width),
      height: Math.round(bounds.height),
      maximized,
    };
  } else {
    persistedWindowState = { ...persistedWindowState, maximized };
  }
}

function flushWindowStateSave(): void {
  if (windowStateSaveTimer) {
    clearTimeout(windowStateSaveTimer);
    windowStateSaveTimer = null;
  }
  saveWindowStateSync(getWindowStateFilePath(), persistedWindowState);
}

function scheduleWindowStateSave(): void {
  if (windowStateSaveTimer) clearTimeout(windowStateSaveTimer);
  windowStateSaveTimer = setTimeout(() => {
    windowStateSaveTimer = null;
    saveWindowStateSync(getWindowStateFilePath(), persistedWindowState);
  }, 250);
  windowStateSaveTimer.unref?.();
}

const pythonRuntime = new RailWatchPythonRuntimeClient();
const grantedExportPaths = new Set<string>();
let allowedRendererUrl = "";
let wakeLock: number | null = null;
let stagedDraft: { config: Record<string, unknown>; revision: number } | null = null;
let draftGeneration = 0;

async function flushStagedDraft(): Promise<void> {
  if (!stagedDraft) return;
  const draft = stagedDraft;
  try {
    await pythonRuntime.request("saveTripDraft", draft, { timeoutMs: 10000 });
  } catch (error) {
    if (!(error instanceof Error && error.message.includes("草稿修订号已过期"))) throw error;
  }
}
let userDataConfigured = false;
if (typeof app.getPath === "function" && typeof app.setPath === "function") {
  configureUnifiedUserData(app as Parameters<typeof configureUnifiedUserData>[0], {
    homeDir: app.getPath("home"),
  });
  userDataConfigured = true;
}
const ownsInstance = app.requestSingleInstanceLock();
if (!ownsInstance) { quitAllowed = true; app.quit(); }
app.on("second-instance", () => {
  if (mainWindow?.isMinimized()) mainWindow.restore();
  mainWindow?.show();
  mainWindow?.focus();
});

function keepAwake(active: boolean) {
  if (active && wakeLock === null) wakeLock = powerSaveBlocker.start("prevent-app-suspension");
  if (!active && wakeLock !== null) { powerSaveBlocker.stop(wakeLock); wakeLock = null; }
}

// Confirmations are rendered by the themed renderer dialog instead of native
// OS message boxes; the gate still lives here and only a renderer response
// (or timeout) lets the command through.
const confirmationBridge = new ConfirmationBridge({
  sendRequest: (request) => {
    if (!mainWindow || mainWindow.isDestroyed()) confirmationReady = false;
    showWindow();
    if (confirmationReady) mainWindow!.webContents.send("railwatch:confirm-request", request);
    else pendingDialogPresentation.push(request);
  },
});

function isTrustedSender(frameUrl: string | null | undefined): boolean {
  return Boolean(frameUrl && allowedRendererUrl && isTrustedRailWatchUrl(frameUrl, allowedRendererUrl));
}

function assertTrustedSender(frameUrl: string | null | undefined): void {
  if (!isTrustedSender(frameUrl)) {
    throw new Error("Refused RailWatch IPC from an untrusted renderer.");
  }
}

function broadcastUpdateState(): void {
  if (!mainWindow || mainWindow.isDestroyed() || !updateManager) {
    return;
  }
  mainWindow.webContents.send("railwatch:update-state", updateManager.getState());
}

function sendToRenderer(channel: string, payload: unknown): void {
  if (!mainWindow || mainWindow.isDestroyed()) {
    return;
  }
  mainWindow.webContents.send(channel, payload);
}

function showWindow(): void {
  if (!mainWindow || mainWindow.isDestroyed()) { createWindow(); return; }
  if (rendererCrashed) { rendererCrashed = false; mainWindow.reload(); }
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.show();
  mainWindow.focus();
}

function updateTray(): void {
  if (!tray) return;
  tray.setToolTip(`RailWatch 12306 · ${lastStatus}`);
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: `状态：${lastStatus}`, enabled: false },
    { label: "显示窗口", click: showWindow },
    { label: "停止监控", click: () => { void pythonRuntime.request("stopMonitor").catch(() => undefined); } },
    { type: "separator" },
    { label: "退出", click: () => { void requestExit(); } },
  ]));
}

/** macOS nativeImage cannot read .ico files. */
function appIconPath(): string {
  return path.join(__dirname, "..", "assets", "images", process.platform === "win32" ? "icon.ico" : "icon.png");
}

function trayIconPath(): string {
  return path.join(__dirname, "..", "assets", "images", trayIconFilename(process.platform));
}

function ensureTray(): boolean {
  if (tray) return true;
  try {
    tray = new Tray(trayIconPath());
    if (!usesTrayMenuOnly(process.platform)) {
      tray.on("double-click", showWindow);
      tray.on("click", showWindow);
    }
    updateTray();
    return true;
  } catch {
    tray = null;
    return false;
  }
}

async function finishExit(force = false): Promise<void> {
  quitAllowed = true;
  clearSplashBackgroundTimer();
  captureWindowBounds();
  flushWindowStateSave();
  try {
    keepAwake(false);
    cleanupUrgentAlert();
    confirmationBridge.cancelAll();
    tray?.destroy(); tray = null;
  } finally {
    try {
      if (force) await pythonRuntime.forceStop();
      else pythonRuntime.stop();
    } finally {
      app.quit();
    }
  }
}

async function requestExit(): Promise<void> {
  if (quitAllowed || exitPending || installPending) return;
  exitPending = true;
  try {
    const activity = await pythonRuntime.request<{ state: string; operation: string | null; unresolved_order: boolean }>("taskActivity", {}, { timeoutMs: 5000 });
    const details = [runtimeContinuityUnknown ? "运行时曾中断，先前任务的最终状态无法确认；请在官方页面核对。" : "", activity.state === "busy" ? `当前操作：${activity.operation || "运行中"}；退出将请求停止并等待收尾。` : "", activity.unresolved_order ? "未完成订单会保留在本地；退出不会取消12306官方订单。" : ""].filter(Boolean);
    if (details.length) {
      const accepted = await confirmationBridge.request({
        title: "确认退出",
        message: `${details.join("\n")}\n\n请在官方页面继续核对和支付。`,
        okText: "退出", cancelText: "取消", danger: true,
      });
      if (!accepted) return;
    }
    await flushStagedDraft();
    const result = await pythonRuntime.request<{ ready: boolean; reason?: string }>("prepareShutdown", { purpose: "quit" }, { timeoutMs: 45000 });
    if (!result.ready) {
      throw new Error(result.reason || "退出准备未完成。");
    }
    await finishExit();
  } catch (error) {
    if (quitAllowed) return;
    const accepted = await confirmationBridge.request({
      title: "无法安全退出",
      message: `退出未完成：${error instanceof Error ? error.message : String(error)}\n\n强制退出将终止本应用运行时，任务最终状态无法确认，尚未保存的草稿可能丢失。已保存的订单记录会保留，退出不会取消官方订单；请在官方页面核对和支付。若受控浏览器仍然打开，请手动关闭。`,
      okText: "强制退出", cancelText: "取消", danger: true,
    });
    if (accepted) await finishExit(true);
  } finally {
    exitPending = false;
  }
}

async function handleWindowClose(event: Electron.Event): Promise<void> {
  if (quitAllowed) return;
  event.preventDefault();
  if (exitPending || closePending || installPending) return;
  closePending = true;
  try {
    try {
      const preferences = await pythonRuntime.request<{ close_to_tray?: boolean }>("loadPreferences", {}, { timeoutMs: 5000 });
      if (preferences.close_to_tray && ensureTray()) {
        if (!trayExplained) {
          const notice = trayCloseNotice(process.platform);
          const acknowledged = await confirmationBridge.request({
            title: notice.title,
            message: notice.message,
            kind: "info", okText: "知道了",
          });
          if (!acknowledged) return;
          trayExplained = true;
        }
        mainWindow?.hide();
        return;
      }
    } catch { /* Unknown runtime state is handled by requestExit. */ }
    await requestExit();
  } finally { closePending = false; }
}

function isRunningUnderRosetta(): boolean {
  return process.platform === "darwin" && Boolean(app.runningUnderARM64Translation);
}

function initializeAutoUpdater(): void {
  const enabled = shouldEnableAutoUpdate({
    isPackaged: app.isPackaged,
    devServerUrl: developmentRendererUrl(app.isPackaged, process.env.VITE_DEV_SERVER_URL),
  });

  // Squirrel.Mac rejects updates for unsigned builds, so macOS only checks and
  // sends users directly to the architecture-matching DMG (with release notes as fallback).
  // Signed auto-install (railwatchMacUpdateMode = auto) needs its own staging-aware
  // updater and is not enabled yet.
  const isDarwin = process.platform === "darwin";
  const installMode: UpdateInstallMode = isDarwin ? "manual" : "auto";
  const updater = process.platform === "win32" ? new RailWatchNsisUpdater() : autoUpdater;
  updater.autoDownload = installMode === "auto";
  updater.autoInstallOnAppQuit = false;
  const macTargetArch = isDarwin ? resolveMacTargetArch(process.arch, isRunningUnderRosetta()) : undefined;

  updateManager = createUpdateManager({
    currentVersion: app.getVersion(),
    updater,
    enabled,
    installMode,
    releaseUrlFor: releaseTagUrl,
    resolveManualDownload: macTargetArch
      ? (info) =>
          resolveMacDmgDownload({
            version: info.version,
            tag: info.tag,
            arch: macTargetArch,
            files: info.files,
          })
      : undefined,
    onStateChange: () => broadcastUpdateState(),
  });

  if (enabled) {
    void updateManager.checkForUpdates();
  }
}

function createWindow(): void {
  rendererCrashed = false;
  if (process.platform === "win32") app.setAppUserModelId("org.railwatch.railwatch12306");
  if (process.platform === "darwin") {
    // Copy, paste, select-all and Cmd+Q only work through the application menu.
    // No view menu: Cmd+R would reload the renderer away from runtime state.
    Menu.setApplicationMenu(Menu.buildFromTemplate([{ role: "appMenu" }, { role: "editMenu" }, { role: "windowMenu" }]));
  } else {
    Menu.setApplicationMenu(null);
  }
  clearSplashBackgroundTimer();
  splashActive = true;
  persistedWindowState = loadWindowState(getWindowStateFilePath());
  const initialTheme = normalizeThemePreference(persistedWindowState.theme);
  persistedWindowState = { ...persistedWindowState, theme: initialTheme };
  if (nativeTheme && "themeSource" in nativeTheme) {
    // Keep the native title bar dark alongside the #101113 startup animation until splash dismisses.
    nativeTheme.themeSource = "dark";
  }
  if (!nativeThemeListenerBound && nativeTheme && typeof nativeTheme.on === "function") {
    nativeThemeListenerBound = true;
    nativeTheme.on("updated", syncWindowThemeBackground);
  }
  const { displays, primaryWorkArea } = getWorkAreaDisplays();
  const layout = resolveWindowLayout(persistedWindowState, displays, primaryWorkArea);
  mainWindow = new BrowserWindow({
    width: layout.width,
    height: layout.height,
    minWidth: layout.minWidth,
    minHeight: layout.minHeight,
    ...(typeof layout.x === "number" && typeof layout.y === "number" ? { x: layout.x, y: layout.y } : {}),
    title: "RailWatch 12306",
    icon: appIconPath(),
    show: false,
    // Startup splash stays uniformly #101113 dark across themes before switching to active theme backdrop.
    backgroundColor: "#101113",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });
  mainWindow.on("close", (event) => {
    captureWindowBounds();
    flushWindowStateSave();
    void handleWindowClose(event);
  });
  const handleWindowMoveOrResize = () => {
    captureWindowBounds();
    scheduleWindowStateSave();
  };
  mainWindow.on("resize", handleWindowMoveOrResize);
  mainWindow.on("move", handleWindowMoveOrResize);
  mainWindow.on("maximize", handleWindowMoveOrResize);
  mainWindow.on("unmaximize", handleWindowMoveOrResize);
  mainWindow.on("closed", () => {
    clearSplashBackgroundTimer();
    mainWindow = null;
    confirmationReady = false;
    pendingDialogPresentation.length = 0;
    confirmationBridge.cancelAll();
  });
  mainWindow.webContents.on("render-process-gone", () => {
    rendererCrashed = true;
    confirmationReady = false;
    pendingDialogPresentation.length = 0;
    confirmationBridge.cancelAll();
  });
  mainWindow.webContents.on("did-start-loading", () => {
    if (confirmationReady) {
      confirmationBridge.cancelAll();
      pendingDialogPresentation.length = 0;
    }
    confirmationReady = false;
  });

  const devServerUrl = developmentRendererUrl(app.isPackaged, process.env.VITE_DEV_SERVER_URL);
  allowedRendererUrl = devServerUrl || pathToFileURL(path.join(__dirname, "..", "dist", "index.html")).toString();
  const window = mainWindow;
  const notifyWindowShown = () => {
    if (!window.isDestroyed() && window.isVisible()) {
      window.webContents.send("railwatch:window-shown");
    }
  };
  window.on("show", () => {
    notifyWindowShown();
    if (splashActive && !splashBackgroundTimer) {
      // Safety fallback if the renderer splash signal is missed; normal handoff happens on railwatch:splash-finished.
      splashBackgroundTimer = setTimeout(completeSplashTransition, 10500);
      splashBackgroundTimer.unref?.();
    }
  });
  // Reloading an already visible window creates a fresh preload listener.
  window.webContents.on("dom-ready", notifyWindowShown);
  window.on("ready-to-show", () => {
    if (window.isDestroyed()) return;
    if (persistedWindowState.maximized && typeof window.maximize === "function") {
      window.maximize();
    }
    window.show();
  });
  const rendererUrl = allowedRendererUrl;
  let loadErrorShown = false;
  const showLoadError = (error: unknown) => {
    if (window.isDestroyed() || loadErrorShown || (error as { errno?: number })?.errno === -3) return;
    loadErrorShown = true;
    completeSplashTransition();
    window.show();
    void dialog.showMessageBox({ type: "error", title: "页面加载失败", message: "RailWatch 页面未能加载。",
      detail: devServerUrl ? "开发服务可能尚未就绪，请启动服务后重试。" : "应用页面可能缺失，请重试或重新安装。",
      buttons: ["重试", "关闭窗口"], defaultId: 0, cancelId: 1,
    }).then(({ response }) => {
      if (window.isDestroyed()) return;
      if (response === 0) { loadErrorShown = false; load(); }
      else window.close();
    }).catch(() => { loadErrorShown = false; });
  };
  const load = () => { void window.loadURL(rendererUrl).catch(showLoadError); };
  window.webContents.on("did-fail-load", (_event, code, description, _url, isMainFrame) => {
    if (isMainFrame && code !== -3) showLoadError(new Error(description));
  });
  load();

  mainWindow.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  mainWindow.webContents.on("will-navigate", (event, url) => {
    if (!isTrustedRailWatchUrl(url, allowedRendererUrl)) {
      event.preventDefault();
    }
  });

  pythonRuntime.on("event", (event: RuntimeEvent) => {
    if (event.event === "state") {
      const state = event.payload as { monitoring?: boolean; status_message?: string };
      keepAwake(Boolean(state?.monitoring));
      lastStatus = state?.status_message || (state?.monitoring ? "监控中" : "空闲");
      updateTray();
    }
    if (event.event === "notify" || event.event === "humanAction") {
      const payload = (event.payload ?? {}) as { priority?: string; title?: string; message?: string; train_code?: string; event_id?: string };
      if (payload.priority === "urgent" && shouldShowUrgentEvent(payload.event_id)) {
        showUrgentAlert(mainWindow, {
          title: payload.title || "RailWatch 提醒",
          message: payload.message || "",
          train_code: payload.train_code,
          kind: event.event === "humanAction" ? "humanAction" : "notify",
        }, alertPreferences);
      } else if (payload.priority === "notice" && shouldShowUrgentEvent(payload.event_id)) {
        showNoticeAlert(mainWindow, { title: payload.title || "RailWatch 提醒", message: payload.message || "" }, alertPreferences);
      }
    }
    sendToRenderer("railwatch:event", event);
  });
  pythonRuntime.on("stderr", (chunk: string) => {
    sendToRenderer("railwatch:event", {
      type: "event",
      event: "log",
      payload: { time: new Date(Date.now() + 8 * 3600000).toISOString().slice(0, 19) + "+08:00", level: "WARN", message: chunk.trim() },
    });
  });
  pythonRuntime.on("runtimeError", (error: Error) => {
    sendToRenderer("railwatch:event", {
      type: "event",
      event: "runtimeError",
      payload: { message: error.message },
    });
  });
  pythonRuntime.on("unavailable", (error: Error) => {
    sendToRenderer("railwatch:event", { type: "event", event: "runtimeUnavailable", payload: { message: error.message } });
  });
  pythonRuntime.on("exit", () => {
    if (!quitAllowed) runtimeContinuityUnknown = true;
    keepAwake(false);
    sendToRenderer("railwatch:event", {
      type: "event",
      event: "runtimeExit",
      payload: { message: "Python runtime exited and will be restarted automatically." },
    });
  });
  pythonRuntime.on("restarted", () => {
    sendToRenderer("railwatch:event", {
      type: "event",
      event: "runtimeRestarted",
      payload: { message: "Python runtime restarted." },
    });
  });
}

app.whenReady().then(() => {
  if (!ownsInstance) return;
  powerMonitor.on("resume", () => { void pythonRuntime.request("systemResumed").catch(() => undefined); });
  registerAlertIpcHandlers(isTrustedSender);
  createWindow();
  void loadInitialRuntimePreferences();
  initializeAutoUpdater();

  app.on("activate", () => {
    showWindow();
  });
});

app.on("window-all-closed", () => {
  // The sound window is not the main window; quitting is handled by requestExit.
});

ipcMain.on("railwatch:stage-draft", (event, draft: unknown) => {
  if (!isTrustedSender(event.senderFrame?.url)) return;
  if (draft === null) { if (stagedDraft) draftGeneration++; stagedDraft = null; return; }
  if (!isRecord(draft) || !isRecord(draft.config) || typeof draft.revision !== "number" ||
      !Number.isSafeInteger(draft.revision) || draft.revision < 1) return;
  if (!stagedDraft || draft.revision >= stagedDraft.revision) {
    if (JSON.stringify(stagedDraft?.config) !== JSON.stringify(draft.config)) draftGeneration++;
    stagedDraft = { config: draft.config, revision: draft.revision };
  }
});

app.on("before-quit", (event) => {
  if (!quitAllowed) { event.preventDefault(); void requestExit(); }
  else cleanupUrgentAlert();
});

ipcMain.on("railwatch:splash-finished", (event) => {
  if (!isTrustedSender(event.senderFrame?.url)) return;
  completeSplashTransition();
});

ipcMain.on("railwatch:confirm-ready", (event) => {
  if (!isTrustedSender(event.senderFrame?.url)) return;
  confirmationReady = true;
  for (const request of pendingDialogPresentation.splice(0)) {
    if (confirmationBridge.isPending(request.id)) sendToRenderer("railwatch:confirm-request", request);
  }
});

ipcMain.on("railwatch:confirm-response", (event, payload: unknown) => {
  if (!isTrustedSender(event.senderFrame?.url)) return;
  if (!isRecord(payload) || typeof payload.id !== "string") {
    return;
  }
  confirmationBridge.respond(payload.id, payload.accepted === true);
});

ipcMain.handle("railwatch:command", async (event, command: string, payload: Record<string, unknown> = {}) => {
  assertTrustedSender(event.senderFrame?.url);
  if (quitAllowed) throw new Error("应用正在退出。");
  if (installPending) throw new Error("正在启动更新安装程序，请稍候。");
  if (!isRailWatchCommand(command)) {
    throw new Error(`Unsupported RailWatch command: ${command}`);
  }
  if (command === "exportTripBundle" || command === "importTripBundle") {
    throw new Error("请通过备份文件对话框操作。");
  }
  if (command === "retryRuntime") {
    pythonRuntime.retry();
    return { ok: true };
  }
  const { confirmed: _untrustedConfirmation, ...normalizedPayload } = isRecord(payload) ? payload : {};
  if (!isExportPathAllowed(command, normalizedPayload, grantedExportPaths)) {
    throw new Error("Export path was not granted by the save dialog.");
  }
  const confirmationGeneration = draftGeneration;
  if (command === "startMonitor" && !runtimePreferencesLoaded) {
    await loadInitialRuntimePreferences();
    if (quitAllowed) throw new Error("应用正在退出。");
    if (installPending) throw new Error("正在启动更新安装程序，请稍候。");
  }
  const confirmation = getCommandConfirmation(command, normalizedPayload, { maintenanceSleep });
  const requestPayload = { ...normalizedPayload };
  if (confirmation) {
    const accepted = await confirmationBridge.request(confirmation);
    if (!accepted) {
      return { cancelled: true };
    }
    if (command === "startMonitor" && confirmationGeneration !== draftGeneration) {
      throw new Error("确认期间行程配置发生变化，请重新核对后启动。");
    }
    requestPayload.confirmed = true;
  }
  consumeExportPathGrant(command, requestPayload, grantedExportPaths);
  // A reloaded renderer starts its revision counter from this response. Commit
  // any newer main-process snapshot first, including edits staged just before
  // a renderer crash, so the new session cannot reuse an older revision.
  if (command === "loadTripState") await flushStagedDraft();
  const result = await pythonRuntime.request(command, requestPayload);
  if (command === "clearLocalData" && isRecord(result) && result.cleared === true) {
    maintenanceSleep = false;
    runtimePreferencesLoaded = true;
    stagedDraft = null;
    draftGeneration++;
    cleanupUrgentAlert();
    if (windowStateSaveTimer) {
      clearTimeout(windowStateSaveTimer);
      windowStateSaveTimer = null;
    }
    persistedWindowState = { theme: "system" };
    if (nativeTheme && "themeSource" in nativeTheme) {
      nativeTheme.themeSource = splashActive ? "dark" : "system";
    }
    syncWindowThemeBackground();
    const userDataDir = typeof app.getPath === "function" ? app.getPath("userData") : "";
    const homeDir = typeof app.getPath === "function" ? app.getPath("home") : undefined;
    const activeSession =
      mainWindow && !mainWindow.isDestroyed() && mainWindow.webContents && "session" in mainWindow.webContents
        ? mainWindow.webContents.session
        : session?.defaultSession;
    const updaterCacheDir = userDataConfigured ? resolveUpdaterCacheDir({ homeDir }) : undefined;
    const failed = await clearElectronLocalData({
      userDataDir,
      updaterCacheDir,
      clearUpdaterCache: Boolean(updaterCacheDir),
      session: activeSession,
    });
    if (failed.length) {
      result.cleanup_pending = true;
      result.warning = [result.warning, `未能清除${failed.join("、")}，请重试清理。`].filter(Boolean).join("\n");
    }
    // A downloaded installer lived in that cache.
    if (updaterCacheDir) updateManager?.discardDownload();
    try { applyRuntimePreferences(await pythonRuntime.request("loadPreferences")); } catch { /* Reload retries preferences. */ }
  }
  if (command === "savePreferences" || command === "loadPreferences") {
    applyRuntimePreferences(result, command === "savePreferences");
  }
  return result;
});

ipcMain.handle("railwatch:preview-alert-sound", async (event, selection: unknown) => {
  assertTrustedSender(event.senderFrame?.url);
  if (quitAllowed) throw new Error("应用正在退出。");
  return previewAlertSound(selection);
});

ipcMain.on("railwatch:stop-sound-preview", (event) => {
  if (isTrustedSender(event.senderFrame?.url)) stopAlertSoundPreview();
});

ipcMain.handle("railwatch:import-alert-sound", async (event) => {
  assertTrustedSender(event.senderFrame?.url);
  if (quitAllowed || !mainWindow || mainWindow.isDestroyed()) throw new Error("应用窗口不可用。");
  const result = await dialog.showOpenDialog(mainWindow, {
    title: "选择自定义提示音", properties: ["openFile"],
    filters: [{ name: "音频文件", extensions: ["wav", "mp3", "ogg", "m4a"] }],
  });
  if (result.canceled || !result.filePaths[0] || quitAllowed) return null;
  const asset = await prepareSoundImport(result.filePaths[0]);
  await validateImportedAlertSound(asset.audio);
  if (quitAllowed) return null;
  await storeImportedSound(asset);
  return { file: asset.file, name: asset.name };
});

ipcMain.handle("railwatch:check-update", async (event) => {
  assertTrustedSender(event.senderFrame?.url);
  if (!updateManager) {
    return {
      ok: false,
      currentVersion: app.getVersion(),
      error: "更新服务尚未初始化。",
      code: "unknown",
    };
  }
  return updateManager.checkForUpdates();
});

ipcMain.handle("railwatch:get-update-state", async (event) => {
  assertTrustedSender(event.senderFrame?.url);
  return updateManager?.getState() ?? { phase: "idle", currentVersion: app.getVersion() };
});

ipcMain.handle("railwatch:install-update", async (event) => {
  assertTrustedSender(event.senderFrame?.url);
  if (installPending || exitPending || quitAllowed) {
    return { ok: false, error: "正在安装更新或退出，请勿重复操作。" };
  }
  if (!updateManager) {
    return { ok: false, error: "更新服务尚未初始化。" };
  }
  if (updateManager.getState().phase !== "downloaded") {
    return { ok: false, error: "当前没有已下载完成的更新。" };
  }
  if (runtimeContinuityUnknown) {
    return { ok: false, error: "运行时曾中断，无法确认任务已安全结束；请退出并重新启动后再安装更新。" };
  }
  installPending = true;
  try {
    await flushStagedDraft();
    const result = await pythonRuntime.request<{ ready: boolean; reason?: string }>("prepareShutdown", { purpose: "install" }, { timeoutMs: 10000 });
    if (!result.ready) return { ok: false, error: result.reason || "活动任务或未完成订单，更新已推迟。" };
    if (!await updateManager.installUpdate()) {
      throw new Error(updateManager.getState().error || "安装程序未能启动，请稍后重试。");
    }
    await finishExit();
    return { ok: true };
  } catch (error) {
    quitAllowed = false;
    let recoveryError = "";
    try {
      await pythonRuntime.request("cancelShutdown", {}, { timeoutMs: 5000 });
    } catch {
      recoveryError = " 后台未能恢复可用状态，请重启应用后再试。";
    }
    return { ok: false, error: `更新安装失败：${error instanceof Error ? error.message : String(error)}${recoveryError}` };
  } finally {
    installPending = false;
  }
});

const TRIP_BUNDLE_FILTER = [{ name: "JSON 备份文件", extensions: ["json"] }];
const MAX_TRIP_BUNDLE_BYTES = 1024 * 1024;

function assertJsonBackupPath(filePath: string): void {
  if (!path.isAbsolute(filePath) || path.extname(filePath).toLowerCase() !== ".json") {
    throw new Error("请选择 .json 备份文件。");
  }
}

async function readTripBundle(filePath: string): Promise<Record<string, unknown>> {
  assertJsonBackupPath(filePath);
  const invalidFile = "备份须为大小不超过 1 MB 的 JSON 文件。";
  if (!(await stat(filePath)).isFile()) throw new Error(invalidFile);
  const file = await open(filePath, constants.O_RDONLY | (constants.O_NONBLOCK ?? 0));
  try {
    const info = await file.stat();
    if (!info.isFile() || info.size > MAX_TRIP_BUNDLE_BYTES) throw new Error(invalidFile);

    // Bound the read even if the file grows after stat.
    const data = Buffer.alloc(info.size + 1);
    let size = 0;
    while (size < data.length) {
      const { bytesRead } = await file.read(data, size, data.length - size, size);
      if (!bytesRead) break;
      size += bytesRead;
    }
    if (size !== info.size) throw new Error("备份文件已发生变化，请重新选择。");
    let bundle: unknown;
    try {
      bundle = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(data.subarray(0, size)));
    } catch {
      throw new Error("备份文件须为有效的 UTF-8 JSON。");
    }
    if (!isRecord(bundle)) throw new Error("备份文件须包含一个 JSON 对象。");
    return bundle;
  } finally {
    await file.close();
  }
}

ipcMain.handle("railwatch:open-data-dir", async (event) => {
  assertTrustedSender(event.senderFrame?.url);
  const unavailable = { ok: false, error: "应用正在退出或安装更新。" };
  if (quitAllowed || installPending) return unavailable;
  try {
    const { data_dir: dataDir } = await pythonRuntime.request<{ data_dir?: string }>("getRuntimeInfo", { probe: false });
    if (quitAllowed || installPending) return unavailable;
    if (typeof dataDir !== "string" || !dataDir.trim() || !path.isAbsolute(dataDir)) {
      return { ok: false, error: "后台未提供有效的数据目录。" };
    }
    const error = await shell.openPath(dataDir);
    return error ? { ok: false, error } : { ok: true };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : String(error) };
  }
});

ipcMain.handle("railwatch:export-trip-bundle", async (event) => {
  assertTrustedSender(event.senderFrame?.url);
  const window = mainWindow;
  if (quitAllowed || installPending || !window || window.isDestroyed()) throw new Error("应用窗口不可用。");
  const bundle = await pythonRuntime.request("exportTripBundle");
  if (!isRecord(bundle)) throw new Error("后台未返回有效的行程备份。");
  if (quitAllowed || installPending || window.isDestroyed()) return { cancelled: true };

  const { canceled, filePath } = await dialog.showSaveDialog(window, {
    title: "导出脱敏备份", defaultPath: "railwatch-trip-backup.json", filters: TRIP_BUNDLE_FILTER,
    properties: ["showOverwriteConfirmation"],
  });
  if (canceled || !filePath || quitAllowed || installPending || window.isDestroyed()) return { cancelled: true };
  assertJsonBackupPath(filePath);
  await writeFile(filePath, JSON.stringify(bundle, null, 2) + "\n", "utf8");
  return { ok: true };
});

ipcMain.handle("railwatch:import-trip-bundle", async (event) => {
  assertTrustedSender(event.senderFrame?.url);
  const window = mainWindow;
  if (quitAllowed || installPending || !window || window.isDestroyed()) throw new Error("应用窗口不可用。");
  const { canceled, filePaths } = await dialog.showOpenDialog(window, {
    title: "选择行程备份", properties: ["openFile"], filters: TRIP_BUNDLE_FILTER,
  });
  if (canceled || !filePaths[0] || quitAllowed || installPending || window.isDestroyed()) return { cancelled: true };
  const bundle = await readTripBundle(filePaths[0]);
  if (quitAllowed || installPending || window.isDestroyed()) return { cancelled: true };
  const accepted = await confirmationBridge.request({
    title: "导入方案与收藏备份",
    message: "仅合并行程方案与路线收藏。备份不含乘车人与密钥，导入方案的自动提交与自动候补默认关闭。",
    okText: "导入备份",
  });
  if (!accepted || quitAllowed || installPending || window.isDestroyed()) return { cancelled: true };
  await pythonRuntime.request("importTripBundle", { bundle });
  return { ok: true };
});

ipcMain.handle("railwatch:export-locations", async (event, defaultPath?: unknown) => {
  assertTrustedSender(event.senderFrame?.url);
  const directory = typeof defaultPath === "string" && path.isAbsolute(defaultPath)
    ? path.dirname(defaultPath) : app.getPath("downloads");
  const drives = await listExportRoots();
  return {
    directory,
    fileName: typeof defaultPath === "string" && defaultPath ? path.basename(defaultPath) : "railwatch-events.txt",
    shortcuts: [
      { name: "下载", path: app.getPath("downloads") },
      { name: "桌面", path: app.getPath("desktop") },
      { name: "文档", path: app.getPath("documents") },
      { name: "日志目录", path: directory },
    ],
    drives,
  };
});

ipcMain.handle("railwatch:export-directory", async (event, directory: unknown) => {
  assertTrustedSender(event.senderFrame?.url);
  return listExportDirectory(directory);
});

ipcMain.handle("railwatch:prepare-log-export", async (event, directory: unknown, fileName: unknown) => {
  assertTrustedSender(event.senderFrame?.url);
  if (quitAllowed) throw new Error("应用正在退出。");
  const target = await validateLogExport(directory, fileName);
  if (target.exists && !await confirmationBridge.request({
    title: "替换已有日志文件？", message: `该文件已存在：\n${target.filePath}\n\n替换后，原文件内容将被覆盖。`,
    okText: "替换文件", cancelText: "保留原文件", danger: true,
  })) return null;
  if (quitAllowed) return null;
  recordExportPathGrant(target.filePath, grantedExportPaths);
  return target.filePath;
});

ipcMain.handle("railwatch:open-external", async (event, url: unknown) => {
  assertTrustedSender(event.senderFrame?.url);
  if (!isAllowedExternalUrl(url)) {
    return { ok: false, error: "External URL is not allowed." };
  }
  await shell.openExternal(url);
  return { ok: true };
});

ipcMain.handle("railwatch:app-info", async (event) => {
  assertTrustedSender(event.senderFrame?.url);
  return {
    appVersion: app.getVersion(),
    electronVersion: process.versions.electron,
    chromeVersion: process.versions.chrome,
    nodeVersion: process.versions.node,
    platform: process.platform,
    arch: process.arch,
    runningUnderARM64Translation: isRunningUnderRosetta(),
  };
});

