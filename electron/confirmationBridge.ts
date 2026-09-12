export type ConfirmationPrompt = {
  title: string;
  message: string;
};

export type ConfirmationRequestPayload = ConfirmationPrompt & {
  id: string;
};

type PendingConfirmation = {
  resolve: (accepted: boolean) => void;
  timer: NodeJS.Timeout;
};

export type ConfirmationBridgeOptions = {
  sendRequest: (request: ConfirmationRequestPayload) => void;
  timeoutMs?: number;
};

const DEFAULT_TIMEOUT_MS = 5 * 60 * 1000;

/**
 * Routes main-process confirmations to the renderer so they are shown with the
 * app theme instead of native OS message boxes. The confirmation gate itself
 * stays in the main process: only a renderer response (or a timeout) settles
 * the pending command, and every response is consumed at most once.
 */
export class ConfirmationBridge {
  private readonly pending = new Map<string, PendingConfirmation>();
  private readonly timeoutMs: number;
  private sequence = 0;

  constructor(private readonly options: ConfirmationBridgeOptions) {
    this.timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  }

  request(prompt: ConfirmationPrompt): Promise<boolean> {
    this.sequence += 1;
    const id = `confirm-${Date.now()}-${this.sequence}`;
    return new Promise((resolve) => {
      const timer = setTimeout(() => {
        this.settle(id, false);
      }, this.timeoutMs);
      this.pending.set(id, { resolve, timer });
      try {
        this.options.sendRequest({ id, title: prompt.title, message: prompt.message });
      } catch {
        this.settle(id, false);
      }
    });
  }

  respond(id: string, accepted: boolean): void {
    this.settle(id, accepted === true);
  }

  /** Decline every pending confirmation, e.g. when the window goes away. */
  cancelAll(): void {
    for (const id of [...this.pending.keys()]) {
      this.settle(id, false);
    }
  }

  private settle(id: string, accepted: boolean): void {
    const pending = this.pending.get(id);
    if (!pending) {
      return;
    }
    clearTimeout(pending.timer);
    this.pending.delete(id);
    pending.resolve(accepted);
  }
}
