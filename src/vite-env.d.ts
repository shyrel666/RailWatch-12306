/// <reference types="vite/client" />

import type { BridgeEvent, UpdateCheckResult, UpdateRuntimeState } from "./types";

declare global {
  interface Window {
    railwatch?: {
      command: <T>(command: string, payload?: Record<string, unknown>) => Promise<T>;
      onEvent: (callback: (event: BridgeEvent) => void) => () => void;
      showSaveDialog: (defaultPath?: string) => Promise<string | null>;
      stopUrgentAlert: () => void;
      checkUpdate: (options?: { force?: boolean }) => Promise<UpdateCheckResult>;
      getUpdateState: () => Promise<UpdateRuntimeState>;
      installUpdate: () => Promise<{ ok: boolean; error?: string }>;
      onUpdateState: (callback: (state: UpdateRuntimeState) => void) => () => void;
    };
  }
}

export {};
