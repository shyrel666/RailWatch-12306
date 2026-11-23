import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { beforeEach, expect, test, vi } from "vitest";

const harness = vi.hoisted(() => ({
  listeners: new Map<string, (...args: any[]) => void>(),
  quit: vi.fn(), request: vi.fn(), stop: vi.fn(), forceStop: vi.fn(),
  confirmDialog: vi.fn(), cleanupAlert: vi.fn(), cancelConfirmations: vi.fn(),
  ready: undefined as undefined | (() => void),
  windowListeners: new Map<string, (...args: any[]) => void>(),
  hide: vi.fn(), show: vi.fn(),
  visible: false, packaged: false,
  ipcListeners: new Map<string, (...args: any[]) => void>(),
  ipcHandlers: new Map<string, (...args: any[]) => any>(),
  webListeners: new Map<string, (...args: any[]) => void>(),
  sendRequest: undefined as undefined | ((request: any) => void),
  send: vi.fn(), reload: vi.fn(), rendererUrl: "",
  loadFailure: undefined as Error | undefined, loadErrorDialog: vi.fn(), closeWindow: vi.fn(),
  installUpdate: vi.fn(), updateState: vi.fn(), discardDownload: vi.fn(),
  setApplicationMenu: vi.fn(), buildFromTemplate: vi.fn(), setAppUserModelId: vi.fn(),
  windowOptions: undefined as any, updaterOptions: undefined as any, autoUpdater: {} as Record<string, unknown>,
  previewSound: vi.fn(), stopPreview: vi.fn(), updateSound: vi.fn(), validateSound: vi.fn(),
  openDialog: vi.fn(), saveDialog: vi.fn(), openPath: vi.fn(), prepareAudio: vi.fn(), storeAudio: vi.fn(),
  clearStorageData: vi.fn(async () => undefined),
  clearCache: vi.fn(async () => undefined),
  userDataDir: "",
  // Unset by default, so importing main never redirects userData or touches the real updater cache.
  homeDir: "", setPath: undefined as undefined | ((name: string, value: string) => void),
  trayInstances: [] as Array<{ icon: unknown; on: ReturnType<typeof vi.fn>; setToolTip: ReturnType<typeof vi.fn>; setContextMenu: ReturnType<typeof vi.fn>; destroy: ReturnType<typeof vi.fn> }>,
  nativeTheme: { themeSource: "system" as "system" | "light" | "dark", shouldUseDarkColors: true },
  nativeThemeListeners: new Map<string, (...args: any[]) => void>(),
  primaryWorkArea: { x: 0, y: 0, width: 1440, height: 900 },
  allWorkAreas: [{ x: 0, y: 0, width: 1440, height: 900 }],
  bounds: { x: 100, y: 80, width: 1200, height: 800 },
  normalBounds: { x: 100, y: 80, width: 1200, height: 800 },
  maximized: false,
  maximize: vi.fn(),
  setBackgroundColor: vi.fn(),
}));
vi.mock("electron", () => ({
  app: { requestSingleInstanceLock: () => true, quit: harness.quit,
    get isPackaged() { return harness.packaged; },
    on: (name: string, listener: (...args: any[]) => void) => harness.listeners.set(name, listener),
    setAppUserModelId: harness.setAppUserModelId, getVersion: () => "0.4.2",
    getPath: (name: string) => (name === "userData" ? harness.userDataDir
      : name === "home" && harness.homeDir ? harness.homeDir : path.resolve(`mock-${name}`)),
    get setPath() { return harness.setPath; },
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
    isMaximized = () => harness.maximized;
    maximize = harness.maximize;
    getBounds = () => ({ ...harness.bounds });
    getNormalBounds = () => ({ ...harness.normalBounds });
    setBackgroundColor = harness.setBackgroundColor;
    focus = vi.fn();
  },
  Menu: { setApplicationMenu: harness.setApplicationMenu, buildFromTemplate: harness.buildFromTemplate },
  nativeImage: { createFromPath: () => ({ resize: () => "tray-image" }) },
  nativeTheme: {
    get themeSource() { return harness.nativeTheme.themeSource; },
    set themeSource(value: "system" | "light" | "dark") { harness.nativeTheme.themeSource = value; },
    get shouldUseDarkColors() { return harness.nativeTheme.shouldUseDarkColors; },
    on: (name: string, listener: (...args: any[]) => void) => harness.nativeThemeListeners.set(name, listener),
  },
  screen: {
    getPrimaryDisplay: () => ({ workArea: harness.primaryWorkArea }),
    getAllDisplays: () => harness.allWorkAreas.map((workArea) => ({ workArea })),
  },
  dialog: { showMessageBox: harness.loadErrorDialog, showOpenDialog: harness.openDialog, showSaveDialog: harness.saveDialog },
  Tray: class {
    icon: unknown;
    on = vi.fn();
    setToolTip = vi.fn();
    setContextMenu = vi.fn();
    destroy = vi.fn();
    constructor(icon: unknown) {
      this.icon = icon;
      harness.trayInstances.push(this);
    }
  },
  powerMonitor: { on: vi.fn() }, powerSaveBlocker: {}, shell: { openPath: harness.openPath },
  session: { defaultSession: { clearStorageData: harness.clearStorageData, clearCache: harness.clearCache } },
}));
vi.mock("electron-updater", () => ({ autoUpdater: harness.autoUpdater }));
vi.mock("../nsisUpdater", () => ({ RailWatchNsisUpdater: class {} }));
vi.mock("../pythonRuntime", () => ({
  RailWatchPythonRuntimeClient: class { request = harness.request; stop = harness.stop; forceStop = harness.forceStop; on = vi.fn(); },
}));
vi.mock("../updateManager", () => ({ createUpdateManager: (options: unknown) => {
  harness.updaterOptions = options;
  return { installUpdate: harness.installUpdate, getState: harness.updateState, discardDownload: harness.discardDownload };
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
  harness.packaged = false;
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
  harness.openDialog.mockResolvedValue({ canceled: true, filePaths: [] });
  harness.saveDialog.mockResolvedValue({ canceled: true });
  harness.openPath.mockResolvedValue("");
  harness.previewSound.mockResolvedValue({ duration_ms: 220 });
  harness.clearStorageData.mockResolvedValue(undefined);
  harness.clearCache.mockResolvedValue(undefined);
  harness.userDataDir = "";
  harness.homeDir = "";
  harness.setPath = undefined;
  harness.trayInstances = [];
  harness.nativeTheme.themeSource = "system";
  harness.nativeTheme.shouldUseDarkColors = true;
  harness.nativeThemeListeners.clear();
  harness.primaryWorkArea = { x: 0, y: 0, width: 1440, height: 900 };
  harness.allWorkAreas = [{ x: 0, y: 0, width: 1440, height: 900 }];
  harness.bounds = { x: 100, y: 80, width: 1200, height: 800 };
  harness.normalBounds = { x: 100, y: 80, width: 1200, height: 800 };
  harness.maximized = false;
  harness.maximize.mockImplementation(() => { harness.maximized = true; });
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
  harness.openDialog.mockResolvedValue({ canceled: false, filePaths: ["C:/Audio/提示音.wav"] });
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

test("opens only the absolute data directory supplied by the runtime", async () => {
  harness.ready!();
  const event = { senderFrame: { url: harness.rendererUrl } };
  const openDataDir = harness.ipcHandlers.get("railwatch:open-data-dir")!;
  const dataDir = path.resolve("trusted-data");
  harness.request.mockImplementation(async command => command === "getRuntimeInfo" ? { data_dir: dataDir } : {});

  await expect(openDataDir({ senderFrame: { url: "https://untrusted.example" } }, path.resolve("other")))
    .rejects.toThrow("untrusted");
  expect(harness.request).not.toHaveBeenCalledWith("getRuntimeInfo", expect.anything());
  expect(harness.openPath).not.toHaveBeenCalled();

  await expect(openDataDir(event, path.resolve("other"))).resolves.toEqual({ ok: true });
  expect(harness.request).toHaveBeenCalledWith("getRuntimeInfo", { probe: false });
  expect(harness.openPath).toHaveBeenCalledExactlyOnceWith(dataDir);
  harness.openPath.mockResolvedValueOnce("无法打开目录");
  await expect(openDataDir(event)).resolves.toEqual({ ok: false, error: "无法打开目录" });
  harness.request.mockResolvedValueOnce({ data_dir: "relative-path" });
  await expect(openDataDir(event)).resolves.toMatchObject({ ok: false });
  expect(harness.openPath).toHaveBeenCalledTimes(2);
});

test("trip backup IPC rejects untrusted senders and requires dedicated handlers", async () => {
  harness.ready!();
  const event = { senderFrame: { url: harness.rendererUrl } };
  for (const channel of ["railwatch:export-trip-bundle", "railwatch:import-trip-bundle"]) {
    const handler = harness.ipcHandlers.get(channel)!;
    await expect(handler({ senderFrame: { url: "https://untrusted.example" } })).rejects.toThrow("untrusted");
    await expect(handler({})).rejects.toThrow("untrusted");
  }
  const command = harness.ipcHandlers.get("railwatch:command")!;
  for (const name of ["exportTripBundle", "importTripBundle"]) {
    await expect(command(event, name, { confirmed: true, bundle: {} })).rejects.toThrow("备份文件对话框");
    expect(harness.request).not.toHaveBeenCalledWith(name, expect.anything());
    expect(harness.request).not.toHaveBeenCalledWith(name);
  }
  await command(event, "loadTripPresets");
  expect(harness.request).toHaveBeenCalledWith("loadTripPresets", {});
  expect(harness.confirmDialog).not.toHaveBeenCalled();
  expect(harness.openDialog).not.toHaveBeenCalled();
  expect(harness.saveDialog).not.toHaveBeenCalled();
});

test("trip backup export writes formatted UTF-8 only to the chosen JSON path", async () => {
  harness.ready!();
  const event = { senderFrame: { url: harness.rendererUrl } };
  const exportBundle = harness.ipcHandlers.get("railwatch:export-trip-bundle")!;
  const root = mkdtempSync(path.join(os.tmpdir(), "railwatch-export-trip-bundle-"));
  const selected = path.join(root, "备份.json");
  const untrusted = path.join(root, "other.json");
  const bundle = { schema_version: 1, presets: [{ name: "往返" }], favorites: [], recent_routes: [] };
  harness.request.mockImplementation(async command => command === "exportTripBundle" ? bundle : {});
  try {
    await expect(exportBundle(event, untrusted)).resolves.toEqual({ cancelled: true });
    expect(existsSync(untrusted)).toBe(false);
    expect(harness.saveDialog).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({
      filters: [{ name: "JSON 备份文件", extensions: ["json"] }],
      properties: ["showOverwriteConfirmation"],
    }));

    harness.saveDialog.mockResolvedValueOnce({ canceled: false, filePath: selected });
    await expect(exportBundle(event, untrusted)).resolves.toEqual({ ok: true });
    expect(readFileSync(selected, "utf8")).toBe(JSON.stringify(bundle, null, 2) + String.fromCharCode(10));
    expect(existsSync(untrusted)).toBe(false);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("trip backup import reads only the chosen file and requires themed confirmation", async () => {
  harness.ready!();
  const event = { senderFrame: { url: harness.rendererUrl } };
  const importBundle = harness.ipcHandlers.get("railwatch:import-trip-bundle")!;
  const root = mkdtempSync(path.join(os.tmpdir(), "railwatch-import-trip-bundle-"));
  const selected = path.join(root, "备份.json");
  const bundle = { schema_version: 1, presets: [{ name: "返程" }], favorites: [], recent_routes: [] };
  try {
    await expect(importBundle(event, { filePaths: [selected], confirmed: true })).resolves.toEqual({ cancelled: true });
    expect(harness.confirmDialog).not.toHaveBeenCalled();

    const sizeLimit = 1024 * 1024;
    const encoded = Buffer.from(JSON.stringify(bundle), "utf8");
    writeFileSync(selected, Buffer.concat([encoded, Buffer.alloc(sizeLimit - encoded.length, 0x20)]));
    harness.openDialog.mockResolvedValue({ canceled: false, filePaths: [selected] });
    await expect(importBundle(event, { confirmed: true, bundle: {} })).resolves.toEqual({ cancelled: true });
    expect(harness.request).not.toHaveBeenCalledWith("importTripBundle", expect.anything());
    expect(harness.openDialog).toHaveBeenLastCalledWith(expect.anything(), expect.objectContaining({
      properties: ["openFile"], filters: [{ name: "JSON 备份文件", extensions: ["json"] }],
    }));
    expect(harness.confirmDialog).toHaveBeenCalledWith(expect.objectContaining({
      message: expect.stringMatching(/仅合并行程方案与路线收藏.*不含乘车人与密钥.*自动提交与自动候补默认关闭/),
    }));

    harness.confirmDialog.mockImplementationOnce(async () => {
      expect(harness.request).not.toHaveBeenCalledWith("importTripBundle", expect.anything());
      return true;
    });
    await expect(importBundle(event, { bundle: {} })).resolves.toEqual({ ok: true });
    expect(harness.request).toHaveBeenCalledWith("importTripBundle", { bundle });
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("invalid and oversized trip backup files never reach confirmation or Python", async () => {
  harness.ready!();
  const event = { senderFrame: { url: harness.rendererUrl } };
  const importBundle = harness.ipcHandlers.get("railwatch:import-trip-bundle")!;
  const root = mkdtempSync(path.join(os.tmpdir(), "railwatch-invalid-trip-bundle-"));
  try {
    const dir = path.join(root, "directory.json");
    mkdirSync(dir);
    harness.openDialog.mockResolvedValueOnce({ canceled: false, filePaths: [dir] });
    await expect(importBundle(event)).rejects.toThrow("1 MB");
    const invalid = [
      { name: "large.json", data: Buffer.alloc(1024 * 1024 + 1), error: "1 MB" },
      { name: "incomplete.json", data: "{", error: "UTF-8 JSON" },
      { name: "invalid-encoding.json", data: Buffer.from([0x22, 0xff, 0x22]), error: "UTF-8 JSON" },
      { name: "array.json", data: "[]", error: "JSON 对象" },
      { name: "null.json", data: "null", error: "JSON 对象" },
      { name: "other.txt", data: "{}", error: ".json" },
    ];
    for (const { name, data, error } of invalid) {
      const filePath = path.join(root, name);
      writeFileSync(filePath, data);
      harness.openDialog.mockResolvedValueOnce({ canceled: false, filePaths: [filePath] });
      await expect(importBundle(event)).rejects.toThrow(error);
    }
    expect(harness.confirmDialog).not.toHaveBeenCalled();
    expect(harness.request).not.toHaveBeenCalledWith("importTripBundle", expect.anything());
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
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
  await vi.waitFor(() => expect(harness.confirmDialog).toHaveBeenCalled());
  harness.ipcListeners.get("railwatch:stage-draft")!(event, { revision: 1, config: { train_code: "G102" } });
  accept(true);
  await expect(pending).rejects.toThrow("配置发生变化");
  expect(harness.request).not.toHaveBeenCalledWith("startMonitor", expect.anything());
});

test("startMonitor waits for in-flight startup preferences and reuses the loaded maintenance choice", async () => {
  let resolvePreferences!: (value: Record<string, unknown>) => void;
  harness.request.mockImplementationOnce(() => new Promise(resolve => { resolvePreferences = resolve; }));
  harness.ready!();
  const event = { senderFrame: { url: harness.rendererUrl } };
  const invoke = harness.ipcHandlers.get("railwatch:command")!;
  const start = invoke(event, "startMonitor", { config: { maintenance_sleep: false } });
  expect(harness.request.mock.calls.map(([name]) => name)).toEqual(["loadPreferences"]);
  expect(harness.confirmDialog).not.toHaveBeenCalled();

  resolvePreferences({ maintenance_sleep: true });
  await expect(start).resolves.toEqual({ cancelled: true });
  expect(harness.confirmDialog).toHaveBeenLastCalledWith(expect.objectContaining({ message: expect.stringContaining("夜间维护休眠") }));
  await invoke(event, "startMonitor", {});
  expect(harness.request.mock.calls.map(([name]) => name)).toEqual(["loadPreferences"]);
  expect(harness.confirmDialog).toHaveBeenLastCalledWith(expect.objectContaining({ message: expect.stringContaining("夜间维护休眠") }));
});

test("startMonitor lazily retries unavailable preferences and ignores a forged renderer choice on fallback", async () => {
  harness.request.mockRejectedValueOnce(new Error("startup preferences unavailable"));
  harness.ready!();
  await new Promise(resolve => setImmediate(resolve));
  const event = { senderFrame: { url: harness.rendererUrl } };
  const invoke = harness.ipcHandlers.get("railwatch:command")!;
  const payload = { config: { maintenance_sleep: true }, maintenanceSleep: true };

  harness.request.mockRejectedValueOnce(new Error("lazy preferences unavailable"));
  await expect(invoke(event, "startMonitor", payload)).resolves.toEqual({ cancelled: true });
  expect(harness.request.mock.calls.map(([name]) => name)).toEqual(["loadPreferences", "loadPreferences"]);
  expect(harness.confirmDialog.mock.lastCall?.[0].message).not.toContain("夜间维护休眠");

  harness.request.mockResolvedValueOnce({ maintenance_sleep: true });
  await invoke(event, "startMonitor", {});
  expect(harness.request.mock.calls.map(([name]) => name)).toEqual(["loadPreferences", "loadPreferences", "loadPreferences"]);
  expect(harness.confirmDialog).toHaveBeenLastCalledWith(expect.objectContaining({ message: expect.stringContaining("夜间维护休眠") }));
});

test("maintenance confirmation follows full preference responses and rejects truthy non-booleans", async () => {
  let resolveStartup!: (value: Record<string, unknown>) => void;
  harness.request.mockImplementationOnce(() => new Promise(resolve => { resolveStartup = resolve; }));
  harness.ready!();
  const event = { senderFrame: { url: harness.rendererUrl } };
  const invoke = harness.ipcHandlers.get("railwatch:command")!;

  harness.request.mockResolvedValueOnce({ maintenance_sleep: true });
  await invoke(event, "savePreferences", { maintenance_sleep: true });
  resolveStartup({ maintenance_sleep: false });
  await new Promise(resolve => setImmediate(resolve));
  await invoke(event, "startMonitor", { config: { maintenance_sleep: false } });
  expect(harness.confirmDialog).toHaveBeenLastCalledWith(expect.objectContaining({ message: expect.stringContaining("夜间维护休眠") }));

  harness.request.mockResolvedValueOnce({ maintenance_sleep: "true" });
  await invoke(event, "loadPreferences");
  await invoke(event, "startMonitor", { config: { maintenance_sleep: true } });
  expect(harness.confirmDialog.mock.lastCall?.[0].message).not.toContain("夜间维护休眠");
  expect(harness.request.mock.calls.map(([name]) => name)).toEqual(["loadPreferences", "savePreferences", "loadPreferences"]);
});

test("a successful local-data reset clears the cached maintenance choice even if its preference refresh fails", async () => {
  harness.request.mockResolvedValueOnce({ maintenance_sleep: true });
  harness.ready!();
  const event = { senderFrame: { url: harness.rendererUrl } };
  const invoke = harness.ipcHandlers.get("railwatch:command")!;
  await invoke(event, "startMonitor", {});
  expect(harness.confirmDialog).toHaveBeenLastCalledWith(expect.objectContaining({ message: expect.stringContaining("夜间维护休眠") }));

  harness.confirmDialog.mockResolvedValueOnce(true);
  harness.request.mockResolvedValueOnce({ cleared: true }).mockRejectedValueOnce(new Error("refresh unavailable"));
  await expect(invoke(event, "clearLocalData")).resolves.toEqual({ cleared: true });
  await invoke(event, "startMonitor", { config: { maintenance_sleep: true } });
  expect(harness.confirmDialog.mock.lastCall?.[0].message).not.toContain("夜间维护休眠");
  expect(harness.request.mock.calls.map(([name]) => name)).toEqual(["loadPreferences", "clearLocalData", "loadPreferences"]);
});

test("a packaged window ignores the inherited development URL for loading and IPC", async () => {
  harness.packaged = true;
  vi.stubEnv("VITE_DEV_SERVER_URL", "http://127.0.0.1:5173");
  try {
    harness.ready!();
    expect(harness.rendererUrl).toMatch(/^file:.*\/dist\/index\.html$/);
    const invoke = harness.ipcHandlers.get("railwatch:command")!;
    await expect(invoke({ senderFrame: { url: "http://127.0.0.1:5173/" } }, "loadTripState", {}))
      .rejects.toThrow("untrusted");
  } finally {
    vi.unstubAllEnvs();
  }
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

test("nativeTheme sync, light startup background, workArea scaling and window state persistence work end-to-end", async () => {
  const tempUserData = mkdtempSync(path.join(os.tmpdir(), "railwatch-main-winstate-"));
  try {
    harness.userDataDir = tempUserData;
    harness.nativeTheme.shouldUseDarkColors = false;
    harness.primaryWorkArea = { x: 0, y: 0, width: 1280, height: 760 };
    harness.allWorkAreas = [harness.primaryWorkArea];
    writeFileSync(
      path.join(tempUserData, "window-state.json"),
      JSON.stringify({ x: 2400, y: 50, width: 1600, height: 1000, maximized: true, theme: "light" }),
      "utf8",
    );

    harness.ready!();
    expect(harness.nativeTheme.themeSource).toBe("dark");
    expect(harness.windowOptions.backgroundColor).toBe("#101113");
    expect(harness.windowOptions.minWidth).toBe(840);
    expect(harness.windowOptions.minHeight).toBe(580);
    expect(harness.windowOptions.width).toBe(1280);
    expect(harness.windowOptions.height).toBe(760);
    expect(harness.windowOptions.x).toBe(0);
    expect(harness.windowOptions.y).toBe(0);

    harness.windowListeners.get("ready-to-show")?.();
    expect(harness.maximize).toHaveBeenCalledTimes(1);
    expect(harness.show).toHaveBeenCalledTimes(1);

    const event = { senderFrame: { url: harness.rendererUrl } };
    harness.request.mockResolvedValueOnce({ theme: "light", notification_settings: { desktop_urgent: true } });
    await harness.ipcHandlers.get("railwatch:command")!(event, "loadPreferences");
    expect(harness.nativeTheme.themeSource).toBe("dark");
    expect(harness.setBackgroundColor).not.toHaveBeenCalled();

    harness.ipcListeners.get("railwatch:splash-finished")!({ senderFrame: { url: "https://evil.example/" } });
    expect(harness.nativeTheme.themeSource).toBe("dark");

    harness.ipcListeners.get("railwatch:splash-finished")!(event);
    expect(harness.nativeTheme.themeSource).toBe("light");
    expect(harness.setBackgroundColor).toHaveBeenCalledWith("#f4f3ef");

    harness.request.mockResolvedValueOnce({ theme: "dark", notification_settings: { desktop_urgent: true } });
    await harness.ipcHandlers.get("railwatch:command")!(event, "savePreferences", { theme: "dark" });
    expect(harness.nativeTheme.themeSource).toBe("dark");
    expect(harness.setBackgroundColor).toHaveBeenCalledWith("#101113");

    harness.confirmDialog.mockResolvedValueOnce(true);
    harness.request.mockResolvedValueOnce({ cleared: true });
    harness.request.mockResolvedValueOnce({ theme: "system", notification_settings: { desktop_urgent: true } });
    await harness.ipcHandlers.get("railwatch:command")!(event, "clearLocalData");
    expect(harness.nativeTheme.themeSource).toBe("system");
    expect(harness.setBackgroundColor).toHaveBeenCalledWith("#f4f3ef");

    harness.nativeTheme.shouldUseDarkColors = true;
    harness.nativeThemeListeners.get("updated")?.();
    expect(harness.setBackgroundColor).toHaveBeenLastCalledWith("#101113");

    harness.maximized = false;
    harness.bounds = { x: 120, y: 90, width: 1024, height: 640 };
    harness.windowListeners.get("close")?.({ preventDefault: vi.fn() });
    const saved = JSON.parse(readFileSync(path.join(tempUserData, "window-state.json"), "utf8"));
    expect(saved).toEqual({
      x: 120,
      y: 90,
      width: 1024,
      height: 640,
      maximized: false,
      theme: "system",
    });
  } finally {
    rmSync(tempUserData, { recursive: true, force: true });
  }
});

test("railwatch:export-locations returns available drives alongside shortcuts", async () => {
  harness.ready!();
  const payload = await harness.ipcHandlers.get("railwatch:export-locations")!(
    { senderFrame: { url: harness.rendererUrl } },
    undefined,
  );
  expect(Array.isArray(payload.drives)).toBe(true);
  expect(payload.drives.length).toBeGreaterThan(0);
  expect(payload.shortcuts.map((item: { name: string }) => item.name)).toContain("下载");
});

test("macOS tray uses template icon, menu-only behavior and menu bar wording", async () => {
  vi.stubGlobal("process", Object.create(process, { platform: { value: "darwin" } }));
  harness.request.mockResolvedValue({ close_to_tray: true });
  harness.confirmDialog.mockResolvedValue(true);
  harness.ready!();
  harness.windowListeners.get("close")!({ preventDefault: vi.fn() });
  await new Promise(resolve => setImmediate(resolve));

  expect(harness.trayInstances).toHaveLength(1);
  expect(String(harness.trayInstances[0].icon)).toMatch(/trayTemplate\.png$/);
  expect(harness.trayInstances[0].on).not.toHaveBeenCalled();
  expect(harness.trayInstances[0].setContextMenu).toHaveBeenCalledTimes(1);
  expect(harness.confirmDialog).toHaveBeenCalledWith(expect.objectContaining({
    title: "已启用关闭到菜单栏",
    message: expect.stringContaining("显示窗口"),
  }));
});

test("Windows tray keeps ico asset, click listeners and tray wording", async () => {
  vi.stubGlobal("process", Object.create(process, { platform: { value: "win32" } }));
  harness.request.mockResolvedValue({ close_to_tray: true });
  harness.confirmDialog.mockResolvedValue(true);
  harness.ready!();
  harness.windowListeners.get("close")!({ preventDefault: vi.fn() });
  await new Promise(resolve => setImmediate(resolve));

  expect(harness.trayInstances).toHaveLength(1);
  expect(String(harness.trayInstances[0].icon)).toMatch(/icon\.ico$/);
  expect(harness.trayInstances[0].on).toHaveBeenCalledWith("double-click", expect.any(Function));
  expect(harness.trayInstances[0].on).toHaveBeenCalledWith("click", expect.any(Function));
  expect(harness.confirmDialog).toHaveBeenCalledWith(expect.objectContaining({
    title: "已启用关闭到托盘",
    message: expect.stringContaining("双击托盘图标"),
  }));
});

test("clearLocalData clears window-state.json and Electron session storage/cache", async () => {
  const { mkdtempSync, existsSync, writeFileSync, rmSync } = await import("node:fs");
  const os = await import("node:os");
  const tempUserData = mkdtempSync(path.join(os.tmpdir(), "railwatch-main-clear-"));
  try {
    harness.userDataDir = tempUserData;
    harness.confirmDialog.mockResolvedValue(true);
    writeFileSync(path.join(tempUserData, "window-state.json"), '{"theme":"dark","width":1200}', "utf8");
    harness.request.mockImplementation(async (cmd: string) => {
      if (cmd === "clearLocalData") return { cleared: true };
      if (cmd === "loadPreferences") return { theme: "system" };
      return {};
    });
    harness.ready!();
    const invoke = harness.ipcHandlers.get("railwatch:command")!;
    const result = await invoke({ senderFrame: { url: harness.rendererUrl } }, "clearLocalData", {});

    expect(result).toEqual({ cleared: true });
    expect(existsSync(path.join(tempUserData, "window-state.json"))).toBe(false);
    expect(harness.clearStorageData).toHaveBeenCalledTimes(1);
    expect(harness.clearCache).toHaveBeenCalledTimes(1);
    harness.clearStorageData.mockRejectedValueOnce(new Error("locked"));
    const partial = await invoke({ senderFrame: { url: harness.rendererUrl } }, "clearLocalData", {});
    expect(partial).toMatchObject({ cleared: true, cleanup_pending: true, warning: expect.stringContaining("会话数据") });
    expect(harness.clearCache).toHaveBeenCalledTimes(2);
    // Without a configured userData directory the updater cache is left alone, and so is its state.
    expect(harness.discardDownload).not.toHaveBeenCalled();
  } finally {
    rmSync(tempUserData, { recursive: true, force: true });
  }
});

test("clearLocalData deletes the downloaded installer and tells the updater it is gone", async () => {
  const home = mkdtempSync(path.join(os.tmpdir(), "railwatch-main-updater-"));
  try {
    // Every per-user location resolves inside the temporary home on each platform.
    vi.stubEnv("LOCALAPPDATA", path.join(home, "AppData", "Local"));
    vi.stubEnv("XDG_DATA_HOME", path.join(home, ".local", "share"));
    vi.stubEnv("XDG_CACHE_HOME", path.join(home, ".cache"));
    harness.homeDir = home;
    harness.setPath = (_name, value) => { harness.userDataDir = value; };
    vi.resetModules();
    await import("../main");  // The unified userData directory is configured on import.
    const { resolveUpdaterCacheDir } = await import("../appDataPaths");
    const cache = resolveUpdaterCacheDir({ homeDir: home });
    expect(cache.startsWith(home + path.sep)).toBe(true);
    const installer = path.join(cache, "pending", "RailWatch-12306-Setup-0.4.3.exe");
    mkdirSync(path.dirname(installer), { recursive: true });
    writeFileSync(installer, "installer");
    harness.request.mockImplementation(async (cmd: string) => {
      if (cmd === "clearLocalData") return { cleared: true };
      if (cmd === "loadPreferences") return { theme: "system" };
      return {};
    });
    harness.ready!();
    const invoke = harness.ipcHandlers.get("railwatch:command")!;
    const event = { senderFrame: { url: harness.rendererUrl } };

    harness.confirmDialog.mockResolvedValue(false);
    expect(await invoke(event, "clearLocalData", {})).toEqual({ cancelled: true });
    expect(existsSync(installer)).toBe(true);
    expect(harness.discardDownload).not.toHaveBeenCalled();

    harness.confirmDialog.mockResolvedValue(true);
    expect(await invoke(event, "clearLocalData", {})).toEqual({ cleared: true });
    expect(existsSync(cache)).toBe(false);
    expect(harness.discardDownload).toHaveBeenCalledOnce();
  } finally {
    vi.unstubAllEnvs();
    rmSync(home, { recursive: true, force: true });
  }
});
