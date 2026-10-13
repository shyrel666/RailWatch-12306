import type { AppInfo, BridgeEvent, ConfirmRequestPayload, NotificationSoundSelection, UpdateCheckResult, UpdateRuntimeState } from "../types";

const missingElectronMessage = "Electron bridge is not available.";

export const railwatchApi = {
  stageDraft(draft: { config: Record<string, unknown>; revision: number } | null) {
    window.railwatch?.stageDraft(draft);
  },
  command<T>(command: string, payload: Record<string, unknown> = {}) {
    if (!window.railwatch) {
      return Promise.reject(new Error(missingElectronMessage));
    }
    return window.railwatch.command<T>(command, payload);
  },
  onEvent(callback: (event: BridgeEvent) => void) {
    if (!window.railwatch) {
      return () => undefined;
    }
    return window.railwatch.onEvent(callback);
  },
  getExportLocations(defaultPath?: string) {
    if (!window.railwatch) return Promise.reject(new Error(missingElectronMessage));
    return window.railwatch.getExportLocations(defaultPath);
  },
  listExportDirectory(directory: string) {
    if (!window.railwatch) return Promise.reject(new Error(missingElectronMessage));
    return window.railwatch.listExportDirectory(directory);
  },
  prepareLogExport(directory: string, fileName: string) {
    if (!window.railwatch) return Promise.reject(new Error(missingElectronMessage));
    return window.railwatch.prepareLogExport(directory, fileName);
  },
  stopUrgentAlert() {
    window.railwatch?.stopUrgentAlert();
  },
  previewAlertSound(selection: NotificationSoundSelection) {
    if (!window.railwatch) return Promise.reject(new Error("请在桌面应用中试听提示音。"));
    if (!window.railwatch.previewAlertSound) return Promise.reject(new Error("请重启桌面应用后使用提示音试听。"));
    return window.railwatch.previewAlertSound(selection);
  },
  stopAlertSoundPreview() {
    window.railwatch?.stopAlertSoundPreview?.();
  },
  importAlertSound() {
    if (!window.railwatch) return Promise.reject(new Error("请在桌面应用中导入提示音。"));
    if (!window.railwatch.importAlertSound) return Promise.reject(new Error("请重启桌面应用后导入提示音。"));
    return window.railwatch.importAlertSound();
  },
  onConfirmRequest(callback: (request: ConfirmRequestPayload) => void) {
    if (!window.railwatch) {
      return () => undefined;
    }
    return window.railwatch.onConfirmRequest(callback);
  },
  respondConfirmation(id: string, accepted: boolean) {
    window.railwatch?.respondConfirmation(id, accepted);
  },
  checkUpdate() {
    if (!window.railwatch) {
      return Promise.reject(new Error(missingElectronMessage));
    }
    return window.railwatch.checkUpdate() as Promise<UpdateCheckResult>;
  },
  getUpdateState() {
    if (!window.railwatch) {
      return Promise.reject(new Error(missingElectronMessage));
    }
    return window.railwatch.getUpdateState() as Promise<UpdateRuntimeState>;
  },
  installUpdate() {
    if (!window.railwatch) {
      return Promise.reject(new Error(missingElectronMessage));
    }
    return window.railwatch.installUpdate() as Promise<{ ok: boolean; error?: string }>;
  },
  onUpdateState(callback: (state: UpdateRuntimeState) => void) {
    if (!window.railwatch) {
      return () => undefined;
    }
    return window.railwatch.onUpdateState(callback);
  },
  openExternal(url: string) {
    if (!window.railwatch) {
      return Promise.reject(new Error(missingElectronMessage));
    }
    return window.railwatch.openExternal(url);
  },
  getAppInfo() {
    if (!window.railwatch) {
      return Promise.reject(new Error(missingElectronMessage));
    }
    return window.railwatch.getAppInfo() as Promise<AppInfo>;
  },
};

