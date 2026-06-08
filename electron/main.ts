import { app, BrowserWindow, Menu, dialog, ipcMain } from "electron";
import path from "node:path";
import { pathToFileURL } from "node:url";
import {
  consumeExportPathGrant,
  getCommandConfirmation,
  isExportPathAllowed,
  isRailWatchCommand,
  isRecord,
  isTrustedRailWatchUrl,
  recordExportPathGrant,
  type ConfirmationPrompt,
} from "./ipcSecurity";
import { RailWatchPythonRuntimeClient, RuntimeEvent } from "./pythonRuntime";

let mainWindow: BrowserWindow | null = null;
const pythonRuntime = new RailWatchPythonRuntimeClient();
const grantedExportPaths = new Set<string>();
let allowedRendererUrl = "";

async function requestMainConfirmation(prompt: ConfirmationPrompt): Promise<boolean> {
  const options = {
    type: "warning" as const,
    title: prompt.title,
    message: prompt.message,
    buttons: ["取消", "确认"],
    defaultId: 1,
    cancelId: 0,
    noLink: true,
  };
  const result = mainWindow ? await dialog.showMessageBox(mainWindow, options) : await dialog.showMessageBox(options);
  return result.response === 1;
}

function assertTrustedSender(frameUrl: string | null | undefined): void {
  if (!frameUrl || !allowedRendererUrl || !isTrustedRailWatchUrl(frameUrl, allowedRendererUrl)) {
    throw new Error("Refused RailWatch IPC from an untrusted renderer.");
  }
}

function createWindow(): void {
  app.setAppUserModelId("org.railwatch.railwatch12306");
  Menu.setApplicationMenu(null);
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1180,
    minHeight: 720,
    title: "RailWatch 12306",
    icon: path.join(__dirname, "..", "assets", "images", "icon.ico"),
    backgroundColor: "#0d1117",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  const devServerUrl = process.env.VITE_DEV_SERVER_URL;
  if (devServerUrl) {
    allowedRendererUrl = devServerUrl;
    mainWindow.loadURL(devServerUrl);
  } else {
    allowedRendererUrl = pathToFileURL(path.join(__dirname, "..", "dist", "index.html")).toString();
    mainWindow.loadURL(allowedRendererUrl);
  }

  mainWindow.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  mainWindow.webContents.on("will-navigate", (event, url) => {
    if (!isTrustedRailWatchUrl(url, allowedRendererUrl)) {
      event.preventDefault();
    }
  });

  pythonRuntime.on("event", (event: RuntimeEvent) => {
    mainWindow?.webContents.send("railwatch:event", event);
  });
  pythonRuntime.on("stderr", (chunk: string) => {
    mainWindow?.webContents.send("railwatch:event", {
      type: "event",
      event: "log",
      payload: { time: new Date().toLocaleTimeString("zh-CN", { hour12: false }), level: "WARN", message: chunk.trim() },
    });
  });
}

app.whenReady().then(() => {
  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on("window-all-closed", () => {
  pythonRuntime.stop();
  if (process.platform !== "darwin") {
    app.quit();
  }
});

ipcMain.handle("railwatch:command", async (event, command: string, payload: Record<string, unknown> = {}) => {
  assertTrustedSender(event.senderFrame?.url);
  if (!isRailWatchCommand(command)) {
    throw new Error(`Unsupported RailWatch command: ${command}`);
  }
  const normalizedPayload = isRecord(payload) ? payload : {};
  if (!isExportPathAllowed(command, normalizedPayload, grantedExportPaths)) {
    throw new Error("Export path was not granted by the save dialog.");
  }
  const confirmation = getCommandConfirmation(command, normalizedPayload);
  const requestPayload = { ...normalizedPayload };
  if (confirmation) {
    const accepted = await requestMainConfirmation(confirmation);
    if (!accepted) {
      return { cancelled: true };
    }
    requestPayload.confirmed = true;
  }
  consumeExportPathGrant(command, requestPayload, grantedExportPaths);
  return pythonRuntime.request(command, requestPayload);
});

ipcMain.handle("railwatch:save-dialog", async (event, defaultPath?: string) => {
  assertTrustedSender(event.senderFrame?.url);
  const options = {
    title: "导出事件",
    defaultPath,
    filters: [
      { name: "文本文件", extensions: ["txt"] },
      { name: "所有文件", extensions: ["*"] },
    ],
  };
  const result = mainWindow ? await dialog.showSaveDialog(mainWindow, options) : await dialog.showSaveDialog(options);
  if (result.canceled) {
    return null;
  }
  recordExportPathGrant(result.filePath, grantedExportPaths);
  return result.filePath;
});
