import { EventEmitter } from "node:events";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { ChildProcessWithoutNullStreams, spawn } from "node:child_process";
import { app } from "electron";

export type RuntimeEvent = {
  type: "event";
  event: string;
  payload: unknown;
};

export type RuntimeResponse = {
  type: "response";
  id: string;
  ok: boolean;
  result?: unknown;
  error?: {
    message: string;
    class?: string;
  };
};

export type RuntimeMessage = RuntimeEvent | RuntimeResponse;

export type RuntimeExitInfo = {
  code: number | null;
  signal: NodeJS.Signals | null;
};

export type RequestOptions = {
  timeoutMs?: number;
};

const DEFAULT_REQUEST_TIMEOUT_MS = 120_000;
const LONG_RUNNING_COMMANDS = new Set([
  "checkEnvironment",
  "openLogin",
  "checkLogin",
  "analyzeQuery",
  "startMonitor",
  "stopMonitor",
  "downloadChromeDriver",
]);
const LONG_RUNNING_TIMEOUT_MS = 600_000;

export class JsonLineDecoder {
  private buffer = "";

  constructor(private readonly onInvalidLine: (line: string, error: unknown) => void = () => undefined) {}

  push(chunk: string): RuntimeMessage[] {
    this.buffer += chunk;
    const lines = this.buffer.split(/\r?\n/);
    this.buffer = lines.pop() ?? "";
    const messages: RuntimeMessage[] = [];
    for (const line of lines.filter(Boolean)) {
      try {
        messages.push(JSON.parse(line) as RuntimeMessage);
      } catch (error) {
        this.onInvalidLine(line, error);
      }
    }
    return messages;
  }
}

type PendingRequest = {
  resolve: (value: unknown) => void;
  reject: (error: Error) => void;
  timeout: NodeJS.Timeout;
};

export class PendingRequests {
  private pending = new Map<string, PendingRequest>();

  create(id: string, timeoutMs: number): Promise<unknown> {
    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        this.reject(id, new Error(`Python runtime request timed out after ${timeoutMs}ms`));
      }, timeoutMs);
      this.pending.set(id, { resolve, reject, timeout });
    });
  }

  resolve(response: RuntimeResponse): void {
    const request = this.pending.get(response.id);
    if (!request) {
      return;
    }
    clearTimeout(request.timeout);
    this.pending.delete(response.id);
    if (response.ok) {
      request.resolve(response.result);
      return;
    }
    request.reject(new Error(response.error?.message || "Python runtime request failed"));
  }

  reject(id: string, error: Error): void {
    const request = this.pending.get(id);
    if (!request) {
      return;
    }
    clearTimeout(request.timeout);
    this.pending.delete(id);
    request.reject(error);
  }

  rejectAll(error: Error): void {
    for (const [id] of this.pending.entries()) {
      this.reject(id, error);
    }
  }
}

export type RuntimeCommand = {
  executable: string;
  args: string[];
  cwd: string;
};

export function createPythonRuntimeCommand(projectRoot: string = path.resolve(__dirname, "..")): RuntimeCommand {
  const packagedExe = path.join(process.resourcesPath || "", "railwatch-runtime", "railwatch_runtime.exe");
  if (app.isPackaged && existsSync(packagedExe)) {
    return { executable: packagedExe, args: [], cwd: path.dirname(packagedExe) };
  }

  const python = process.env.RAILWATCH_PYTHON || "python";
  const runtimeScript = path.join(projectRoot, "railwatch_runtime.py");
  return { executable: python, args: [runtimeScript], cwd: projectRoot };
}

export function resolveRailWatchAppVersion(projectRoot: string = path.resolve(__dirname, "..")): string {
  const candidates = [path.join(projectRoot, "package.json")];
  const appPath = typeof app?.getAppPath === "function" ? app.getAppPath() : "";
  if (appPath) {
    candidates.push(path.join(appPath, "package.json"));
  }

  for (const candidate of candidates) {
    try {
      const payload = JSON.parse(readFileSync(candidate, "utf8")) as { version?: string };
      const version = payload.version?.trim();
      if (version) {
        return version;
      }
    } catch {
      continue;
    }
  }

  return "未知";
}

export class RailWatchPythonRuntimeClient extends EventEmitter {
  private child: ChildProcessWithoutNullStreams | null = null;
  private readonly decoder: JsonLineDecoder;
  private readonly pending = new PendingRequests();
  private nextId = 1;
  private intentionalStop = false;
  private restartTimer: NodeJS.Timeout | null = null;

  constructor(private readonly command: RuntimeCommand = createPythonRuntimeCommand()) {
    super();
    this.appVersion = resolveRailWatchAppVersion(path.resolve(__dirname, ".."));
    this.decoder = new JsonLineDecoder((line) => {
      this.emit("stderr", `Ignored non-JSON stdout from Python runtime: ${line}`);
    });
  }

  private readonly appVersion: string;

  start(): void {
    if (this.child) {
      return;
    }
    this.intentionalStop = false;
    this.child = spawn(this.command.executable, this.command.args, {
      cwd: this.command.cwd,
      stdio: "pipe",
      windowsHide: true,
      env: {
        ...process.env,
        RAILWATCH_APP_VERSION: this.appVersion,
      },
    });
    this.child.stdout.setEncoding("utf8");
    this.child.stdout.on("data", (chunk: string) => {
      for (const message of this.decoder.push(chunk)) {
        this.handleMessage(message);
      }
    });
    this.child.stderr.setEncoding("utf8");
    this.child.stderr.on("data", (chunk: string) => {
      this.emit("stderr", chunk);
    });
    this.child.on("error", (error) => {
      this.pending.rejectAll(error);
      this.emit("runtimeError", error);
    });
    this.child.on("exit", (code, signal) => {
      const error = new Error(`Python runtime exited (${code ?? signal ?? "unknown"})`);
      this.pending.rejectAll(error);
      this.child = null;
      const exitInfo: RuntimeExitInfo = { code, signal };
      this.emit("exit", exitInfo);
      if (!this.intentionalStop) {
        this.scheduleRestart();
      }
    });
    this.emit("started");
  }

  async request<T = unknown>(
    command: string,
    payload: Record<string, unknown> = {},
    options: RequestOptions = {},
  ): Promise<T> {
    this.start();
    if (!this.child) {
      throw new Error("Python runtime failed to start");
    }
    const timeoutMs =
      options.timeoutMs ?? (LONG_RUNNING_COMMANDS.has(command) ? LONG_RUNNING_TIMEOUT_MS : DEFAULT_REQUEST_TIMEOUT_MS);
    const id = String(this.nextId++);
    const promise = this.pending.create(id, timeoutMs) as Promise<T>;
    this.child.stdin.write(JSON.stringify({ id, command, payload }) + "\n");
    return promise;
  }

  stop(): void {
    this.intentionalStop = true;
    if (this.restartTimer) {
      clearTimeout(this.restartTimer);
      this.restartTimer = null;
    }
    if (!this.child) {
      return;
    }
    this.child.kill();
    this.child = null;
  }

  private scheduleRestart(): void {
    if (this.restartTimer || this.intentionalStop) {
      return;
    }
    this.restartTimer = setTimeout(() => {
      this.restartTimer = null;
      if (!this.intentionalStop) {
        this.start();
        this.emit("restarted");
      }
    }, 1000);
  }

  private handleMessage(message: RuntimeMessage): void {
    if (message.type === "event") {
      this.emit("event", message);
      return;
    }
    this.pending.resolve(message);
  }
}
