import { EventEmitter } from "node:events";
import { existsSync } from "node:fs";
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

export class JsonLineDecoder {
  private buffer = "";

  push(chunk: string): RuntimeMessage[] {
    this.buffer += chunk;
    const lines = this.buffer.split(/\r?\n/);
    this.buffer = lines.pop() ?? "";
    return lines.filter(Boolean).map((line) => JSON.parse(line) as RuntimeMessage);
  }
}

type PendingRequest = {
  resolve: (value: unknown) => void;
  reject: (error: Error) => void;
};

export class PendingRequests {
  private pending = new Map<string, PendingRequest>();

  create(id: string): Promise<unknown> {
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
    });
  }

  resolve(response: RuntimeResponse): void {
    const request = this.pending.get(response.id);
    if (!request) {
      return;
    }
    this.pending.delete(response.id);
    if (response.ok) {
      request.resolve(response.result);
      return;
    }
    request.reject(new Error(response.error?.message || "Python runtime request failed"));
  }

  rejectAll(error: Error): void {
    for (const request of this.pending.values()) {
      request.reject(error);
    }
    this.pending.clear();
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

export class RailWatchPythonRuntimeClient extends EventEmitter {
  private child: ChildProcessWithoutNullStreams | null = null;
  private readonly decoder = new JsonLineDecoder();
  private readonly pending = new PendingRequests();
  private nextId = 1;

  constructor(private readonly command: RuntimeCommand = createPythonRuntimeCommand()) {
    super();
  }

  start(): void {
    if (this.child) {
      return;
    }
    this.child = spawn(this.command.executable, this.command.args, {
      cwd: this.command.cwd,
      stdio: "pipe",
      windowsHide: true,
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
      this.emit("error", error);
    });
    this.child.on("exit", (code, signal) => {
      const error = new Error(`Python runtime exited (${code ?? signal ?? "unknown"})`);
      this.pending.rejectAll(error);
      this.child = null;
      this.emit("exit", { code, signal });
    });
  }

  async request<T = unknown>(command: string, payload: Record<string, unknown> = {}): Promise<T> {
    this.start();
    if (!this.child) {
      throw new Error("Python runtime failed to start");
    }
    const id = String(this.nextId++);
    const promise = this.pending.create(id) as Promise<T>;
    this.child.stdin.write(JSON.stringify({ id, command, payload }) + "\n");
    return promise;
  }

  stop(): void {
    if (!this.child) {
      return;
    }
    this.child.kill();
    this.child = null;
  }

  private handleMessage(message: RuntimeMessage): void {
    if (message.type === "event") {
      this.emit("event", message);
      return;
    }
    this.pending.resolve(message);
  }
}
