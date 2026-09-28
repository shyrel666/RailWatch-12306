import { contextBridge, ipcRenderer } from "electron";
import { isRailWatchCommand } from "./ipcSecurity";
import type { ConfirmationRequestPayload } from "./confirmationBridge";

contextBridge.exposeInMainWorld("railwatch", {
  command: <T>(command: string, payload: Record<string, unknown> = {}) => {
    if (!isRailWatchCommand(command)) {
      return Promise.reject(new Error(`Unsupported RailWatch command: ${command}`));
    }
    return ipcRenderer.invoke("railwatch:command", command, payload) as Promise<T>;
  },
  stageDraft: (draft: { config: Record<string, unknown>; revision: number } | null) => {
    ipcRenderer.send("railwatch:stage-draft", draft);
  },
  onEvent: (callback: (event: unknown) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, payload: unknown) => callback(payload);
    ipcRenderer.on("railwatch:event", listener);
    return () => ipcRenderer.removeListener("railwatch:event", listener);
  },
  getExportLocations: (defaultPath?: string) => ipcRenderer.invoke("railwatch:export-locations", defaultPath),
  listExportDirectory: (directory: string) => ipcRenderer.invoke("railwatch:export-directory", directory),
  prepareLogExport: (directory: string, fileName: string) => ipcRenderer.invoke("railwatch:prepare-log-export", directory, fileName),
  stopUrgentAlert: () => {
    ipcRenderer.send("railwatch:stop-alert");
  },
  onConfirmRequest: (callback: (request: ConfirmationRequestPayload) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, payload: unknown) => callback(payload as ConfirmationRequestPayload);
    ipcRenderer.on("railwatch:confirm-request", listener);
    ipcRenderer.send("railwatch:confirm-ready");
    return () => ipcRenderer.removeListener("railwatch:confirm-request", listener);
  },
  respondConfirmation: (id: string, accepted: boolean) => {
    ipcRenderer.send("railwatch:confirm-response", { id, accepted });
  },
  checkUpdate: () => {
    return ipcRenderer.invoke("railwatch:check-update");
  },
  getUpdateState: () => {
    return ipcRenderer.invoke("railwatch:get-update-state");
  },
  installUpdate: () => {
    return ipcRenderer.invoke("railwatch:install-update");
  },
  onUpdateState: (callback: (state: unknown) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, payload: unknown) => callback(payload);
    ipcRenderer.on("railwatch:update-state", listener);
    return () => ipcRenderer.removeListener("railwatch:update-state", listener);
  },
  openExternal: (url: string) => {
    return ipcRenderer.invoke("railwatch:open-external", url) as Promise<{ ok: boolean; error?: string }>;
  },
  getAppInfo: () => {
    return ipcRenderer.invoke("railwatch:app-info") as Promise<{
      appVersion: string;
      electronVersion: string;
      chromeVersion: string;
      nodeVersion: string;
      platform: string;
      arch: string;
    }>;
  },
});

