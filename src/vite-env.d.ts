/// <reference types="vite/client" />

import type { AppInfo, BridgeEvent, ConfirmRequestPayload, ExportLocations, ExportDirectory, UpdateCheckResult, UpdateRuntimeState } from "./types";

declare global {
  interface Window {
    railwatch?: {
      command: <T>(command: string, payload?: Record<string, unknown>) => Promise<T>;
      stageDraft: (draft: { config: Record<string, unknown>; revision: number } | null) => void;
      onEvent: (callback: (event: BridgeEvent) => void) => () => void;
      getExportLocations: (defaultPath?: string) => Promise<ExportLocations>;
      listExportDirectory: (directory: string) => Promise<ExportDirectory>;
      prepareLogExport: (directory: string, fileName: string) => Promise<string | null>;
      stopUrgentAlert: () => void;
      onConfirmRequest: (callback: (request: ConfirmRequestPayload) => void) => () => void;
      respondConfirmation: (id: string, accepted: boolean) => void;
      checkUpdate: () => Promise<UpdateCheckResult>;
      getUpdateState: () => Promise<UpdateRuntimeState>;
      installUpdate: () => Promise<{ ok: boolean; error?: string }>;
      onUpdateState: (callback: (state: UpdateRuntimeState) => void) => () => void;
      openExternal: (url: string) => Promise<{ ok: boolean; error?: string }>;
      getAppInfo: () => Promise<AppInfo>;
    };
  }
}

export {};

