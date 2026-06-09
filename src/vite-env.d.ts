/// <reference types="vite/client" />

import type { BridgeEvent } from "./types";

declare global {
  interface Window {
    railwatch?: {
      command: <T>(command: string, payload?: Record<string, unknown>) => Promise<T>;
      onEvent: (callback: (event: BridgeEvent) => void) => () => void;
      showSaveDialog: (defaultPath?: string) => Promise<string | null>;
      stopUrgentAlert: () => void;
    };
  }
}

export {};
