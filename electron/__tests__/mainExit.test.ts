import { beforeEach, expect, test, vi } from "vitest";

const harness = vi.hoisted(() => ({
  listeners: new Map<string, (...args: any[]) => void>(),
  quit: vi.fn(), request: vi.fn(), stop: vi.fn(), forceStop: vi.fn(),
  confirmDialog: vi.fn(), cleanupAlert: vi.fn(), cancelConfirmations: vi.fn(),
  ready: undefined as undefined | (() => void),
  windowListeners: new Map<string, (...args: any[]) => void>(),
  hide: vi.fn(), show: vi.fn(),
  visible: false,
  ipcListeners: new Map<string, (...args: any[]) => void>(),
  ipcHandlers: new Map<string, (...args: any[]) => any>(),
  webListeners: new Map<string, (...args: any[]) => void>(),
  sendRequest: undefined as undefined | ((request: any) => void),
  send: vi.fn(), reload: vi.fn(), rendererUrl: "",
  loadFailure: undefined as Error | undefined, loadErrorDialog: vi.fn(), closeWindow: vi.fn(),
  installUpdate: vi.fn(), updateState: vi.fn(),
  setApplicationMenu: vi.fn(), buildFromTemplate: vi.fn(), setAppUserModelId: vi.fn(),
  windowOptions: undefined as any, updaterOptions: undefined as any, autoUpdater: {} as Record<string, unknown>,
  previewSound: vi.fn(), stopPreview: vi.fn(), updateSound: vi.fn(), validateSound: vi.fn(),
  openAudio: vi.fn(), prepareAudio: vi.fn(), storeAudio: vi.fn(),
}));
vi.mock("electron", () => ({
  app: { requestSingleInstanceLock: () => true, quit: harness.quit,
    on: (name: string, listener: (...args: any[]) => void) => harness.listeners.set(name, listener),
    setAppUserModelId: harness.setAppUserModelId, getVersion: () => "0.4.2",
    whenReady: () => ({ then: (callback: () => void) => { harness.ready = callback; } }) },
  ipcMain: { on: (name: string, listener: (...args: any[]) => void) => harness.ipcListeners.set(name, listener),
    handle: (name: string, listener: (...args: any[]) => any) => harness.ipcHandlers.set(name, listener) },
  BrowserWindow: class {
    constructor(options: unknown) { harness.windowOptions = options; }
    webContents = { on: (name: string, listener: (...args: any[]) => void) => harness.webListeners.set(name, listener), setWindowOpenHandler: vi.fn(), send: harness.send };
    on = (name: string, listener: (...args: any[]) => void) => harness.windowListeners.set(name, listener);
    loadURL = (url: string) => { harness.rendererUrl = url; return harness.loadFailure ? Promise.reject(harness.loadFailure) : Promise.resolve(); }; hide = harness.hide; show = harness.show;
    close = harness.closeWindow;
    reload = harness.reload;
    isDestroyed = () => false; isMinimized = () => false;
    isVisible = () => harness.visible;
    focus = vi.fn();
  },
  Menu: { setApplicationMenu: harness.setApplicationMenu, buildFromTemplate: harness.buildFromTemplate },
  nativeImage: { createFromPath: () => ({ resize: () => "tray-image" }) },
  dialog: { showMessageBox: harness.loadErrorDialog, showOpenDialog: harness.openAudio },
  Tray: class { on = vi.fn(); setToolTip = vi.fn(); setContextMenu = vi.fn(); destroy = vi.fn(); },
  powerMonitor: { on: vi.fn() }, powerSaveBlocker: {}, shell: {},
}));
vi.mock("electron-updater", () => ({ autoUpdater: harness.autoUpdater }));
vi.mock("../nsisUpdater", () => ({ RailWatchNsisUpdater: class {} }));
vi.mock("../pythonRuntime", () => ({
  RailWatchPythonRuntimeClient: class { request = harness.request; stop = harness.stop; forceStop = harness.forceStop; on = vi.fn(); },
}));
vi.mock("../updateManager", () => ({ createUpdateManager: (options: unknown) => {
  harness.updaterOptions = options;
  return { installUpdate: harness.installUpdate, getState: harness.updateState };
}, shouldEnableAutoUpdate: vi.fn() }));
vi.mock("../alertManager", () => ({ cleanupUrgentAlert: harness.cleanupAlert,
  registerAlertIpcHandlers: vi.fn(), showUrgentAlert: vi.fn(), stopUrgentAlertLoop: vi.fn(),
  previewAlertSound: harness.previewSound, stopAlertSoundPreview: harness.stopPreview,
  updateUrgentAlertSound: harness.updateSound, validateImportedAlertSound: harness.validateSound }));
vi.mock("../alertSoundFiles", async (original) => ({
  ...await original<typeof import("../alertSoundFiles")>(),
  prepareSoundImport: harness.prepareAudio, storeImportedSound: harness.storeAudio,
}));
vi.mock("../confirmationBridge", () => ({
  ConfirmationBridge: class {
    constructor(options: { sendRequest: (request: any) => void }) { harness.sendRequest = options.sendRequest; }
    request = harness.confirmDialog; cancelAll = harness.cancelConfirmations;
    isPending = () => true;
  },
}));

async function exitAttempt() {
  const event = { preventDefault: vi.fn() };
  harness.listeners.get("before-quit")!(event);
  await new Promise(resolve => setImmediate(resolve));
  return event;
}

beforeEach(async () => {
  vi.resetModules();
  vi.resetAllMocks();
  vi.unstubAllGlobals();
  for (const key of Object.keys(harness.autoUpdater)) delete harness.autoUpdater[key];
  harness.listeners.clear();
  harness.windowListeners.clear();
  harness.webListeners.clear();
  harness.visible = false;
  harness.show.mockImplementation(() => {
    harness.visible = true;
    harness.windowListeners.get("show")?.();
  });
  harness.hide.mockImplementation(() => { harness.visible = false; });
  harness.ipcListeners.clear();
  harness.ipcHandlers.clear();
  harness.request.mockImplementation(async command => command === "taskActivity"
    ? { state: "idle", unresolved_order: false } : { ready: true });
  harness.confirmDialog.mockResolvedValue(false);
  harness.forceStop.mockResolvedValue(undefined);
  harness.loadFailure = undefined;
  harness.loadErrorDialog.mockResolvedValue({ response: 1 });
  harness.updateState.mockReturnValue({ phase: "downloaded" });
  harness.installUpdate.mockResolvedValue(true);
  harness.openAudio.mockResolvedValue({ canceled: true, filePaths: [] });
  harness.previewSound.mockResolvedValue({ duration_ms: 220 });
  await import("../main");
});

test("saved audio preferences update the urgent player without starting a preview", async () => {
  harness.ready!();
  const settings = { desktop_urgent: true, sound_loop: true, window_attention: true, sound_tone: "alarm" };
  harness.request.mockResolvedValue({ notification_settings: settings });
  await harness.ipcHandlers.get("railwatch:command")!({ senderFrame: { url: harness.rendererUrl } },
    "savePreferences", { notification_settings: { sound_tone: "alarm" } });
  expect(harness.updateSound).toHaveBeenCalledWith(expect.objectContaining({ sound_tone: "alarm" }));
  expect(harness.previewSound).not.toHaveBeenCalled();
});

test("sound preview stays local and only a trusted renderer can play, stop or import audio", async () => {
  harness.ready!();
  const trusted = { senderFrame: { url: harness.rendererUrl } };
  const untrusted = { senderFrame: { url: "https://untrusted.example" } };
  const preview = harness.ipcHandlers.get("railwatch:preview-alert-sound")!;
  const importSound = harness.ipcHandlers.get("railwatch:import-alert-sound")!;
  await expect(preview(untrusted, { sound_tone: "beep" })).rejects.toThrow("untrusted");
  await expect(importSound(untrusted)).rejects.toThrow("untrusted");
  harness.ipcListeners.get("railwatch:stop-sound-preview")!(untrusted);
  expect(harness.stopPreview).not.toHaveBeenCalled();
  const requests = harness.request.mock.calls.length;
  await expect(preview(trusted, { sound_tone: "chime" })).resolves.toEqual({ duration_ms: 220 });
  expect(harness.request).toHaveBeenCalledTimes(requests);
  expect(harness.previewSound).toHaveBeenCalledWith({ sound_tone: "chime" });
  harness.ipcListeners.get("railwatch:stop-sound-preview")!(trusted);
  expect(harness.stopPreview).toHaveBeenCalledOnce();
  await expect(importSound(trusted)).resolves.toBeNull();
  expect(harness.prepareAudio).not.toHaveBeenCalled();
});

test("custom audio is decoded before storing and a decoder error never imports the file", async () => {
  harness.ready!();
  const event = { senderFrame: { url: harness.rendererUrl } };
  const asset = { file: "a".repeat(64) + ".wav", name: "提示音.wav", audio: "base64-audio", data: Buffer.from("fixture") };
  harness.openAudio.mockResolvedValue({ canceled: false, filePaths: ["C:/Audio/提示音.wav"] });
  harness.prepareAudio.mockResolvedValue(asset);
  const importSound = harness.ipcHandlers.get("railwatch:import-alert-sound")!;
  await expect(importSound(event)).resolves.toEqual({ file: asset.file, name: asset.name });
  expect(harness.validateSound).toHaveBeenCalledWith(asset.audio);
  expect(harness.validateSound.mock.invocationCallOrder[0]).toBeLessThan(harness.storeAudio.mock.invocationCallOrder[0]);
  harness.storeAudio.mockClear();
  harness.validateSound.mockRejectedValue(new Error("音频无效"));
  await expect(importSound(event)).rejects.toThrow("音频无效");
  expect(harness.storeAudio).not.toHaveBeenCalled();
});

test("update installation keeps the runtime alive until launch acknowledgement", async () => {
  harness.ready!();
  let launched!: (value: boolean) => void;
  harness.installUpdate.mockImplementation(() => new Promise<boolean>(resolve => { launched = resolve; }));
  const event = { senderFrame: { url: harness.rendererUrl } };
  const install = harness.ipcHandlers.get("railwatch:install-update")!;
  const pending = install(event);
  await new Promise(resolve => setImmediate(resolve));
  expect(harness.request).toHaveBeenCalledWith("prepareShutdown", { purpose: "install" }, { timeoutMs: 10000 });
  expect(harness.stop).not.toHaveBeenCalled();
  expect(harness.quit).not.toHaveBeenCalled();
  expect((await install(event)).ok).toBe(false);
  const quitting = await exitAttempt();
  expect(quitting.preventDefault).toHaveBeenCalled();
  expect(harness.request).not.toHaveBeenCalledWith("prepareShutdown", { purpose: "quit" }, expect.anything());
  launched(true);
  expect(await pending).toEqual({ ok: true });
  expect(harness.installUpdate).toHaveBeenCalledOnce();
  expect(harness.stop).toHaveBeenCalledOnce();
  expect(harness.quit).toHaveBeenCalledOnce();
});

test("asynchronous install failure restores admission without stopping or quitting", async () => {
  harness.ready!();
  harness.installUpdate.mockImplementation(() => new Promise(resolve => setImmediate(() => {
    harness.updateState.mockReturnValue({ phase: "error", error: "installer spawn failed" });
    resolve(false);
  })));
  const event = { senderFrame: { url: harness.rendererUrl } };
  const result = await harness.ipcHandlers.get("railwatch:install-update")!(event);
  expect(result).toEqual({ ok: false, error: expect.stringContaining("installer spawn failed") });
  expect(harness.request).toHaveBeenCalledWith("cancelShutdown", {}, { timeoutMs: 5000 });
  expect(harness.stop).not.toHaveBeenCalled();
  expect(harness.quit).not.toHaveBeenCalled();
  await expect(harness.ipcHandlers.get("railwatch:command")!(event, "getRuntimeInfo")).resolves.toBeTruthy();
});

test("an active task or unresolved order prevents installer launch", async () => {
  harness.ready!();
  harness.request.mockResolvedValue({ ready: false, reason: "未完成订单" });
  const event = { senderFrame: { url: harness.rendererUrl } };
  expect(await harness.ipcHandlers.get("railwatch:install-update")!(event)).toEqual({ ok: false, error: "未完成订单" });
  expect(harness.installUpdate).not.toHaveBeenCalled();
  expect(harness.stop).not.toHaveBeenCalled();
  expect(harness.quit).not.toHaveBeenCalled();
});

test("failed shutdown recovery is reported instead of claiming the app is ready", async () => {
  harness.ready!();
  harness.installUpdate.mockResolvedValue(false);
  harness.request.mockImplementation(async command => {
    if (command === "cancelShutdown") throw new Error("runtime unavailable");
    return { ready: true };
  });
  const event = { senderFrame: { url: harness.rendererUrl } };
  const result = await harness.ipcHandlers.get("railwatch:install-update")!(event);
  expect(result.ok).toBe(false);
  expect(result.error).toContain("后台未能恢复");
  expect(harness.stop).not.toHaveBeenCalled();
  expect(harness.quit).not.toHaveBeenCalled();
});

test("idle exit completes normal shutdown without force or confirmation", async () => {
  await exitAttempt();
  expect(harness.request).toHaveBeenCalledWith("prepareShutdown", { purpose: "quit" }, { timeoutMs: 45000 });
  expect(harness.confirmDialog).not.toHaveBeenCalled();
  expect(harness.stop).toHaveBeenCalledOnce();
  expect(harness.forceStop).not.toHaveBeenCalled();
  expect(harness.quit).toHaveBeenCalledOnce();
});

test("cancelling active-task exit leaves the task running", async () => {
  harness.request.mockResolvedValue({ state: "busy", operation: "submitting", unresolved_order: true });
  await exitAttempt();
  expect(harness.request).toHaveBeenCalledTimes(1);
  expect(harness.stop).not.toHaveBeenCalled();
  expect(harness.forceStop).not.toHaveBeenCalled();
  expect(harness.quit).not.toHaveBeenCalled();
});

test("unavailable runtime can be cancelled then explicitly force-exited", async () => {
  harness.request.mockRejectedValue(new Error("runtime cannot start"));
  await exitAttempt();
  expect(harness.quit).not.toHaveBeenCalled();
  expect(harness.forceStop).not.toHaveBeenCalled();
  expect(harness.confirmDialog).toHaveBeenCalledWith(expect.objectContaining({
    okText: "强制退出", cancelText: "取消", danger: true,
    message: expect.stringContaining("退出不会取消官方订单"),
  }));
  harness.confirmDialog.mockResolvedValue(true);
  await exitAttempt();
  expect(harness.forceStop).toHaveBeenCalledOnce();
  expect(harness.cleanupAlert).toHaveBeenCalledOnce();
  expect(harness.cancelConfirmations).toHaveBeenCalledOnce();
  expect(harness.quit).toHaveBeenCalledOnce();
  expect((await exitAttempt()).preventDefault).not.toHaveBeenCalled();
});

test.each(["not-ready", "timeout"])("failed shutdown (%s) offers force exit without retrying submission", async failure => {
  harness.request.mockImplementation(async command => {
    if (command === "taskActivity") return { state: "idle", unresolved_order: false };
    if (failure === "timeout") throw new Error("request timed out");
    return { ready: false, reason: "任务停止超时" };
  });
  harness.confirmDialog.mockResolvedValue(true);
  await exitAttempt();
  expect(harness.forceStop).toHaveBeenCalledOnce();
  expect(harness.quit).toHaveBeenCalledOnce();
  expect(harness.request.mock.calls.map(call => call[0])).toEqual(["taskActivity", "prepareShutdown"]);
});

test("repeated exit requests share one pending force-exit confirmation", async () => {
  harness.request.mockRejectedValue(new Error("runtime unavailable"));
  let answer!: (value: boolean) => void;
  harness.confirmDialog.mockImplementation(() => new Promise(resolve => { answer = resolve; }));
  await exitAttempt();
  await exitAttempt();
  expect(harness.confirmDialog).toHaveBeenCalledOnce();
  answer(true);
  await new Promise(resolve => setImmediate(resolve));
  expect(harness.forceStop).toHaveBeenCalledOnce();
  expect(harness.quit).toHaveBeenCalledOnce();
});

test("renderer confirmed flag cannot bypass the single main-process summary", async () => {
  harness.ready!();
  const event = { senderFrame: { url: harness.rendererUrl } };
  const command = harness.ipcHandlers.get("railwatch:command")!;
  const payload = { confirmed: true, config: { auto_submit: true, train_code: "G101" }, expected_dates: ["2026-09-27"] };
  await expect(command(event, "startMonitor", payload)).resolves.toEqual({ cancelled: true });
  expect(harness.request).not.toHaveBeenCalledWith("startMonitor", expect.anything());
  harness.confirmDialog.mockResolvedValue(true);
  await command(event, "startMonitor", payload);
  expect(harness.confirmDialog).toHaveBeenLastCalledWith(expect.objectContaining({ message: expect.stringContaining("G101") }));
  expect(harness.request).toHaveBeenCalledWith("startMonitor", expect.objectContaining({ confirmed: true, config: payload.config }));
});

test("draft edits during main-process confirmation prevent startup", async () => {
  harness.ready!();
  const event = { senderFrame: { url: harness.rendererUrl } };
  let accept!: (accepted: boolean) => void;
  harness.confirmDialog.mockImplementation(() => new Promise(resolve => { accept = resolve; }));
  const pending = harness.ipcHandlers.get("railwatch:command")!(event, "startMonitor", { config: { train_code: "G101" } });
  harness.ipcListeners.get("railwatch:stage-draft")!(event, { revision: 1, config: { train_code: "G102" } });
  accept(true);
  await expect(pending).rejects.toThrow("配置发生变化");
  expect(harness.request).not.toHaveBeenCalledWith("startMonitor", expect.anything());
});

test("untrusted fire-and-forget IPC is ignored without throwing", () => {
  harness.ready!();
  for (const name of ["railwatch:stage-draft", "railwatch:confirm-ready", "railwatch:confirm-response"]) {
    expect(() => harness.ipcListeners.get(name)!({ senderFrame: { url: "https://untrusted.example" } }, {})).not.toThrow();
  }
});

test("the startup window stays hidden until its first renderer frame is ready", async () => {
  harness.ready!();
  expect(harness.windowOptions).toEqual(expect.objectContaining({ show: false }));
  await new Promise(resolve => setImmediate(resolve));
  expect(harness.show).not.toHaveBeenCalled();
  harness.webListeners.get("dom-ready")!();
  expect(harness.send).not.toHaveBeenCalledWith("railwatch:window-shown");

  harness.windowListeners.get("ready-to-show")!();

  expect(harness.show).toHaveBeenCalledOnce();
  expect(harness.send).toHaveBeenCalledWith("railwatch:window-shown");
});

test("a visible window notifies a fresh preload after a renderer reload", () => {
  harness.ready!();
  harness.windowListeners.get("ready-to-show")!();
  harness.send.mockClear();

  harness.webListeners.get("dom-ready")!();

  expect(harness.send).toHaveBeenCalledWith("railwatch:window-shown");
});

test("cancelled and subframe loads keep the startup window hidden", () => {
  harness.ready!();
  const failLoad = harness.webListeners.get("did-fail-load")!;
  failLoad({}, -3, "cancelled", harness.rendererUrl, true);
  failLoad({}, -6, "missing frame", harness.rendererUrl, false);

  expect(harness.show).not.toHaveBeenCalled();
  expect(harness.loadErrorDialog).not.toHaveBeenCalled();
});

test("load failures reveal the startup window and show one error despite duplicate main-frame events", async () => {
  harness.loadFailure = new Error("missing page");
  harness.ready!();
  harness.webListeners.get("did-fail-load")!({}, -6, "missing page", harness.rendererUrl, true);
  await new Promise(resolve => setImmediate(resolve));
  expect(harness.show).toHaveBeenCalledOnce();
  expect(harness.loadErrorDialog).toHaveBeenCalledOnce();
  expect(harness.show.mock.invocationCallOrder[0]).toBeLessThan(harness.loadErrorDialog.mock.invocationCallOrder[0]);
  expect(harness.closeWindow).toHaveBeenCalledOnce();
});

test("first close-to-tray explains the behavior through the themed info dialog", async () => {
  harness.request.mockResolvedValue({ close_to_tray: true });
  harness.confirmDialog.mockResolvedValue(true);
  harness.ready!();
  const event = { preventDefault: vi.fn() };
  harness.windowListeners.get("close")!(event);
  await new Promise(resolve => setImmediate(resolve));
  expect(harness.confirmDialog).toHaveBeenCalledWith(expect.objectContaining({ kind: "info", okText: "知道了" }));
  expect(harness.hide).toHaveBeenCalledOnce();
  expect(harness.quit).not.toHaveBeenCalled();
  harness.windowListeners.get("close")!(event);
  await new Promise(resolve => setImmediate(resolve));
  expect(harness.confirmDialog).toHaveBeenCalledOnce();
  expect(harness.hide).toHaveBeenCalledTimes(2);
});

test("dismissing the first tray notice keeps the window visible", async () => {
  harness.request.mockResolvedValue({ close_to_tray: true });
  harness.confirmDialog.mockResolvedValue(false);
  harness.ready!();
  harness.windowListeners.get("close")!({ preventDefault: vi.fn() });
  await new Promise(resolve => setImmediate(resolve));
  expect(harness.hide).not.toHaveBeenCalled();
  expect(harness.quit).not.toHaveBeenCalled();
});

test("a prompt requested before renderer readiness is delivered once after subscription", () => {
  const prompt = { id: "exit-1", title: "确认退出", message: "仍有任务" };
  harness.sendRequest!(prompt);
  expect(harness.send).not.toHaveBeenCalled();
  harness.ipcListeners.get("railwatch:confirm-ready")!({ senderFrame: { url: harness.rendererUrl } });
  expect(harness.send).toHaveBeenCalledWith("railwatch:confirm-request", prompt);
  harness.ipcListeners.get("railwatch:confirm-ready")!({ senderFrame: { url: harness.rendererUrl } });
  expect(harness.send).toHaveBeenCalledOnce();
});

test("renderer crash cancels pending decisions and reloads before showing another prompt", () => {
  harness.ready!();
  harness.webListeners.get("render-process-gone")!();
  expect(harness.cancelConfirmations).toHaveBeenCalledOnce();
  harness.sendRequest!({ id: "recovery", title: "无法安全退出", message: "请选择" });
  expect(harness.reload).toHaveBeenCalledOnce();
  const prompts = () => harness.send.mock.calls.filter(([channel]) => channel === "railwatch:confirm-request");
  expect(prompts()).toHaveLength(0);
  harness.ipcListeners.get("railwatch:confirm-ready")!({ senderFrame: { url: harness.rendererUrl } });
  expect(prompts()).toHaveLength(1);
});

test("renderer recovery loads the latest staged revision before accepting new edits", async () => {
  harness.ready!();
  const event = { senderFrame: { url: harness.rendererUrl } };
  const stage = harness.ipcListeners.get("railwatch:stage-draft")!;
  const command = harness.ipcHandlers.get("railwatch:command")!;
  let disk = { schema_version: 1, revision: 5, saved_at: 1, config: { train_code: "G100" } };
  harness.request.mockImplementation(async (name, payload) => {
    if (name === "saveTripDraft") {
      if (payload.revision <= disk.revision) throw new Error("草稿修订号已过期，请重新加载最新草稿。");
      disk = { ...disk, ...payload, saved_at: disk.saved_at + 1 };
      return disk;
    }
    if (name === "loadTripState") return { saved_config: {}, saved_at: 0,
      draft: { status: "available", draft: disk, warning: null } };
    return name === "taskActivity" ? { state: "idle", unresolved_order: false } : { ready: true };
  });
  stage(event, { revision: 10, config: { train_code: "G101" } });
  harness.webListeners.get("render-process-gone")!();
  const restored = await command(event, "loadTripState");
  expect(restored.draft.draft).toMatchObject({ revision: 10, config: { train_code: "G101" } });
  const next = { revision: restored.draft.draft.revision + 1, config: { train_code: "G102" } };
  stage(event, next);
  await command(event, "saveTripDraft", next);
  await exitAttempt();
  expect(disk).toMatchObject(next);
  const writes = harness.request.mock.calls.filter(call => call[0] === "saveTripDraft");
  expect(writes.at(-1)?.[1]).toEqual(next);
  expect(harness.quit).toHaveBeenCalledOnce();
});

test("a failed recovery flush cannot initialize the renderer with an older revision", async () => {
  harness.ready!();
  const event = { senderFrame: { url: harness.rendererUrl } };
  harness.ipcListeners.get("railwatch:stage-draft")!(event, { revision: 8, config: { train_code: "G101" } });
  harness.request.mockRejectedValue(new Error("disk full"));
  await expect(harness.ipcHandlers.get("railwatch:command")!(event, "loadTripState")).rejects.toThrow("disk full");
  expect(harness.request).not.toHaveBeenCalledWith("loadTripState", expect.anything());
});

test("macOS gets an edit menu, a PNG icon and release-page-only updates", async () => {
  vi.stubGlobal("process", Object.create(process, { platform: { value: "darwin" } }));
  harness.ready!();
  expect(harness.buildFromTemplate).toHaveBeenCalledWith([{ role: "appMenu" }, { role: "editMenu" }, { role: "windowMenu" }]);
  expect(harness.setApplicationMenu).not.toHaveBeenCalledWith(null);
  expect(harness.setAppUserModelId).not.toHaveBeenCalled();
  expect(harness.windowOptions.icon).toMatch(/icon\.png$/);
  expect(harness.autoUpdater.autoDownload).toBe(false);
  expect(harness.updaterOptions.installMode).toBe("manual");
  expect(harness.updaterOptions.releaseUrlFor("0.6.1")).toBe("https://github.com/shyrel666/RailWatch-12306/releases/tag/v0.6.1");
  // Cmd+Q and the app menu's Quit reach before-quit, which keeps the safe exit path.
  const quitting = await exitAttempt();
  expect(quitting.preventDefault).toHaveBeenCalled();
  expect(harness.request).toHaveBeenCalledWith("prepareShutdown", { purpose: "quit" }, { timeoutMs: 45000 });
});

test("Windows keeps no application menu, the ICO icon and NSIS auto-download", async () => {
  vi.stubGlobal("process", Object.create(process, { platform: { value: "win32" } }));
  harness.ready!();
  expect(harness.setApplicationMenu).toHaveBeenCalledWith(null);
  expect(harness.setAppUserModelId).toHaveBeenCalledWith("org.railwatch.railwatch12306");
  expect(harness.windowOptions.icon).toMatch(/icon\.ico$/);
  expect(harness.updaterOptions.installMode).toBe("auto");
});
