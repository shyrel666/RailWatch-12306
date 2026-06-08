import { contextBridge, ipcRenderer } from "electron";
import { isRailWatchCommand } from "./ipcSecurity";

contextBridge.exposeInMainWorld("railwatch", {
  command: <T>(command: string, payload: Record<string, unknown> = {}) => {
    if (!isRailWatchCommand(command)) {
      return Promise.reject(new Error(`Unsupported RailWatch command: ${command}`));
    }
    return ipcRenderer.invoke("railwatch:command", command, payload) as Promise<T>;
  },
  onEvent: (callback: (event: unknown) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, payload: unknown) => callback(payload);
    ipcRenderer.on("railwatch:event", listener);
    return () => ipcRenderer.removeListener("railwatch:event", listener);
  },
  showSaveDialog: (defaultPath?: string) => {
    return ipcRenderer.invoke("railwatch:save-dialog", defaultPath) as Promise<string | null>;
  },
});
