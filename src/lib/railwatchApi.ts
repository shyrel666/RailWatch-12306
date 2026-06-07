import type { BridgeEvent } from "../types";

const missingElectronMessage = "Electron bridge is not available.";

export const railwatchApi = {
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
  showSaveDialog(defaultPath?: string) {
    if (!window.railwatch) {
      return Promise.resolve(null);
    }
    return window.railwatch.showSaveDialog(defaultPath);
  },
};
