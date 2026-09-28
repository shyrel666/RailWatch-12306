import { EventEmitter } from "node:events";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { ChildProcessWithoutNullStreams, execFile, spawn } from "node:child_process";
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

  reset(): void {
    this.buffer = "";
  }

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
  private disposed = false;
  private restartTimer: NodeJS.Timeout | null = null;
  private stableTimer: NodeJS.Timeout | null = null;
  private restartAttempts = 0;
  private unavailable = false;
  private manualRecovery = false;

  constructor(private readonly command: RuntimeCommand = createPythonRuntimeCommand()) {
    super();
    this.appVersion = resolveRailWatchAppVersion(path.resolve(__dirname, ".."));
    this.decoder = new JsonLineDecoder((line) => {
      this.emit("stderr", `Ignored non-JSON stdout from Python runtime: ${line}`);
    });
  }

  private readonly appVersion: string;

  start(): void {
    if (this.disposed) throw new Error("Python runtime is shutting down");
    if (this.child) {
      return;
    }
    if (this.unavailable) throw new Error("运行时无法启动，请点击重试运行时。");
    if (this.restartTimer) {
      throw new Error("运行时正在等待恢复，请稍后重试。");
    }
    this.intentionalStop = false;
    this.decoder.reset();
    const child = spawn(this.command.executable, this.command.args, {
      cwd: this.command.cwd,
      stdio: "pipe",
      windowsHide: true,
      env: {
        ...process.env,
        RAILWATCH_APP_VERSION: this.appVersion,
      },
    });
    this.child = child;
    const finish = (error: Error, code: number | null, signal: NodeJS.Signals | null) => {
      if (this.child !== child) return;
      if (this.stableTimer) clearTimeout(this.stableTimer);
      this.stableTimer = null;
      this.pending.rejectAll(error);
      this.child = null;
      this.emit("exit", { code, signal } satisfies RuntimeExitInfo);
      if (!this.intentionalStop) this.scheduleRestart();
    };
    child.stdout.setEncoding("utf8");
    child.stdout.on("data", (chunk: string) => {
      if (this.child !== child) return;
      for (const message of this.decoder.push(chunk)) {
        this.handleMessage(message);
      }
    });
    child.stderr.setEncoding("utf8");
    child.stderr.on("data", (chunk: string) => {
      if (this.child !== child) return;
      this.emit("stderr", chunk);
    });
    child.on("error", (error) => {
      if (this.child !== child) return;
      this.emit("runtimeError", error);
      finish(error, null, null);
    });
    child.stdin.on("error", (error) => {
      if (this.child !== child) return;
      this.emit("runtimeError", error);
      finish(error, null, null);
      child.kill();
    });
    child.on("exit", (code, signal) => {
      const error = new Error(`Python runtime exited (${code ?? signal ?? "unknown"})`);
      finish(error, code, signal);
    });
    child.once("spawn", () => {
      if (this.child !== child) return;
      this.emit("started");
      const recovering = this.restartAttempts > 0 || this.manualRecovery;
      void this.request("getRuntimeInfo", {}, { timeoutMs: 10000 }).then(info => {
        if (this.child !== child) return;
        if (!info || typeof info !== "object" || !("state" in info) || !info.state || typeof info.state !== "object") {
          throw new Error("Runtime readiness response is invalid");
        }
        this.emit("ready", info);
        if (recovering) this.emit("restarted");
        this.manualRecovery = false;
        this.stableTimer = setTimeout(() => { this.restartAttempts = 0; this.stableTimer = null; }, 30000);
      }).catch(error => {
        if (this.child !== child) return;
        finish(error instanceof Error ? error : new Error("Runtime readiness failed"), null, null);
        child.kill();
      });
    });
  }

  retry(): void {
    if (this.child) return;
    if (this.restartTimer) clearTimeout(this.restartTimer);
    this.restartTimer = null;
    this.unavailable = false;
    this.restartAttempts = 0;
    this.manualRecovery = true;
    this.start();
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
    this.child.stdin.write(JSON.stringify({ id, command, payload }) + "\n", (error) => {
      if (error) this.pending.reject(id, error);
    });
    return promise;
  }

  stop(): void {
    this.detachChild()?.kill();
  }

  async forceStop(): Promise<void> {
    // Permanent shutdown: periodic UI requests cannot restart the runtime.
    this.disposed = true;
    const child = this.detachChild();
    if (!child) return;
    if (process.platform === "win32" && child.pid) {
      // Terminate only this live child and its descendants, never Chrome by
      // image name. Kill the tree before killing its root so ancestry survives.
      await new Promise<void>((resolve) => {
        execFile("taskkill", ["/PID", String(child.pid), "/T", "/F"],
          { windowsHide: true, timeout: 5000 }, (error) => {
            if (error) child.kill();
            resolve();
          });
      });
    } else {
      child.kill("SIGKILL");
    }
  }

  private detachChild(): ChildProcessWithoutNullStreams | null {
    this.intentionalStop = true;
    if (this.stableTimer) clearTimeout(this.stableTimer);
    this.stableTimer = null;
    if (this.restartTimer) {
      clearTimeout(this.restartTimer);
      this.restartTimer = null;
    }
    const child = this.child;
    this.child = null;
    this.pending.rejectAll(new Error("Python runtime stopped"));
    return child;
  }

  private scheduleRestart(): void {
    if (this.restartTimer || this.intentionalStop) {
      return;
    }
    if (this.restartAttempts >= 5) {
      this.unavailable = true;
      this.emit("unavailable", new Error("运行时连续启动失败，自动恢复已暂停，请点击重试运行时。"));
      return;
    }
    const delay = Math.min(30000, 1000 * 2 ** this.restartAttempts++);
    this.restartTimer = setTimeout(() => {
      this.restartTimer = null;
      if (!this.intentionalStop) {
        this.start();
      }
    }, delay);
  }

  private handleMessage(message: RuntimeMessage): void {
    if (message.type === "event") {
      this.emit("event", message);
      return;
    }
    this.pending.resolve(message);
  }
}
