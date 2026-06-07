import { app, BrowserWindow, dialog, ipcMain } from "electron";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { RailWatchPythonRuntimeClient, RuntimeEvent } from "./pythonRuntime";

let mainWindow: BrowserWindow | null = null;
const pythonRuntime = new RailWatchPythonRuntimeClient();

function createWindow(): void {
  app.setAppUserModelId("org.railwatch.railwatch12306");
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1180,
    minHeight: 720,
    title: "RailWatch 12306",
    icon: path.join(__dirname, "..", "assets", "images", "icon.ico"),
    backgroundColor: "#eef2f0",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  const devServerUrl = process.env.VITE_DEV_SERVER_URL;
  if (devServerUrl) {
    mainWindow.loadURL(devServerUrl);
  } else {
    mainWindow.loadURL(pathToFileURL(path.join(__dirname, "..", "dist", "index.html")).toString());
  }

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

ipcMain.handle("railwatch:command", async (_event, command: string, payload: Record<string, unknown> = {}) => {
  return pythonRuntime.request(command, payload);
});

ipcMain.handle("railwatch:save-dialog", async (_event, defaultPath?: string) => {
  const options = {
    title: "导出事件",
    defaultPath,
    filters: [
      { name: "文本文件", extensions: ["txt"] },
      { name: "所有文件", extensions: ["*"] },
    ],
  };
  const result = mainWindow ? await dialog.showSaveDialog(mainWindow, options) : await dialog.showSaveDialog(options);
  return result.canceled ? null : result.filePath;
});
