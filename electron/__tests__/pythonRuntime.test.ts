import { readFileSync } from "node:fs";
import { EventEmitter } from "node:events";
import { PassThrough } from "node:stream";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

const { spawn } = vi.hoisted(() => ({ spawn: vi.fn() }));
vi.mock("node:child_process", () => ({ spawn, execFile: vi.fn() }));
vi.mock("electron", () => ({ app: { isPackaged: false, getAppPath: () => process.cwd() } }));
import {
  JsonLineDecoder,
  PendingRequests,
  RUNTIME_MISSING_MESSAGE,
  createPythonRuntimeCommand,
  packagedRuntimeExecutable,
  resolveRailWatchAppVersion,
  RailWatchPythonRuntimeClient,
} from "../pythonRuntime";

describe("resolveRailWatchAppVersion", () => {
  test("reads the app version from the project package.json", () => {
    const packageJson = JSON.parse(readFileSync(path.resolve(__dirname, "../../package.json"), "utf8")) as { version: string };

    expect(resolveRailWatchAppVersion()).toBe(packageJson.version);
  });
});

describe("JsonLineDecoder", () => {
  test("parses complete and split JSON lines", () => {
    const decoder = new JsonLineDecoder();

    const first = decoder.push('{"type":"event","event":"log"}\n{"type"');
    const second = decoder.push(':"response","id":"1","ok":true}\n');

    expect(first).toEqual([{ type: "event", event: "log" }]);
    expect(second).toEqual([{ type: "response", id: "1", ok: true }]);
  });

  test("ignores invalid JSON lines without throwing", () => {
    const invalidLines: string[] = [];
    const decoder = new JsonLineDecoder((line) => invalidLines.push(line));

    const messages = decoder.push('not-json\n{"type":"response","id":"1","ok":true}\n');

    expect(messages).toEqual([{ type: "response", id: "1", ok: true }]);
    expect(invalidLines).toEqual(["not-json"]);
  });
});

describe("PendingRequests", () => {
  test("resolves only the matching response id", async () => {
    const pending = new PendingRequests();
    const first = pending.create("1", 5000);
    const second = pending.create("2", 5000);

    pending.resolve({ type: "response", id: "2", ok: true, result: { value: 2 } });
    pending.resolve({ type: "response", id: "1", ok: true, result: { value: 1 } });

    await expect(first).resolves.toEqual({ value: 1 });
    await expect(second).resolves.toEqual({ value: 2 });
  });

  test("rejects error responses with the runtime message", async () => {
    const pending = new PendingRequests();
    const promise = pending.create("1", 5000);

    pending.resolve({
      type: "response",
      id: "1",
      ok: false,
      error: { message: "环境检查失败", class: "RuntimeError" },
    });

    await expect(promise).rejects.toThrow("环境检查失败");
  });
});

describe("environment request progress timeout", () => {
  let runtime: RailWatchPythonRuntimeClient;
  let child: EventEmitter & { stdout: PassThrough; stderr: PassThrough; stdin: PassThrough; kill: ReturnType<typeof vi.fn> };

  function event(payload: unknown, name = "environmentProgress") {
    child.stdout.write(JSON.stringify({ type: "event", event: name, payload }) + "\n");
  }

  beforeEach(() => {
    vi.useFakeTimers();
    child = Object.assign(new EventEmitter(), {
      stdout: new PassThrough(), stderr: new PassThrough(), stdin: new PassThrough(), kill: vi.fn(),
    });
    spawn.mockReset().mockReturnValue(child);
    runtime = new RailWatchPythonRuntimeClient({ executable: "python", args: [], cwd: process.cwd() });
  });

  afterEach(() => {
    runtime.stop();
    vi.useRealTimers();
  });

  test.each(["checkEnvironment", "downloadChromeDriver"])("%s keeps waiting beyond ten minutes while progress arrives", async operation => {
    const settled = vi.fn();
    const result = runtime.request(operation);
    void result.then(settled, settled);
    for (let index = 0; index < 3; index++) {
      await vi.advanceTimersByTimeAsync(550_000);
      event({ operation, status: "running", stage: "downloading", downloaded_bytes: index + 1 });
      expect(settled).not.toHaveBeenCalled();
    }
    child.stdout.write('{"type":"response","id":"1","ok":true,"result":"ready"}\n');
    await expect(result).resolves.toBe("ready");
    event({ operation, status: "running" });
    expect(vi.getTimerCount()).toBe(0);
  });

  test("a download still times out ten minutes after its last progress", async () => {
    const rejected = expect(runtime.request("downloadChromeDriver")).rejects.toThrow("timed out");
    await vi.advanceTimersByTimeAsync(500_000);
    event({ operation: "downloadChromeDriver", status: "running" });
    await vi.advanceTimersByTimeAsync(599_999);
    expect(vi.getTimerCount()).toBe(1);
    await vi.advanceTimersByTimeAsync(1);
    await rejected;
    event({ operation: "downloadChromeDriver", status: "running" });
    expect(vi.getTimerCount()).toBe(0);
  });

  test("an explicit timeout remains a fixed deadline despite progress", async () => {
    const rejected = expect(runtime.request("checkEnvironment", {}, { timeoutMs: 1000 })).rejects.toThrow("1000ms");
    await vi.advanceTimersByTimeAsync(999);
    event({ operation: "checkEnvironment", status: "running" });
    await vi.advanceTimersByTimeAsync(1);
    await rejected;
    expect(vi.getTimerCount()).toBe(0);
  });

  test.each([
    ["another operation", { operation: "downloadChromeDriver", status: "running" }, "environmentProgress"],
    ["success", { operation: "checkEnvironment", status: "success" }, "environmentProgress"],
    ["error", { operation: "checkEnvironment", status: "error" }, "environmentProgress"],
    ["missing status", { operation: "checkEnvironment" }, "environmentProgress"],
    ["invalid operation", { operation: 123, status: "running" }, "environmentProgress"],
    ["null payload", null, "environmentProgress"],
    ["unrelated event", { operation: "checkEnvironment", status: "running" }, "log"],
  ])("%s cannot extend the environment request", async (_label, payload, name) => {
    const rejected = expect(runtime.request("checkEnvironment")).rejects.toThrow("600000ms");
    await vi.advanceTimersByTimeAsync(599_999);
    event(payload, name as string);
    await vi.advanceTimersByTimeAsync(1);
    await rejected;
  });

  test.each([["rehearse", 600_000], ["loadConfig", 120_000]] as const)("%s keeps its existing fixed deadline", async (command, timeout) => {
    const rejected = expect(runtime.request(command)).rejects.toThrow(`${timeout}ms`);
    await vi.advanceTimersByTimeAsync(timeout - 1);
    event({ operation: command, status: "running" });
    event({ operation: "checkEnvironment", status: "running" });
    await vi.advanceTimersByTimeAsync(1);
    await rejected;
  });

  test("runtime exit rejects an extended request and stale progress cannot revive it", async () => {
    const rejected = expect(runtime.request("checkEnvironment")).rejects.toThrow("exited");
    await vi.advanceTimersByTimeAsync(550_000);
    event({ operation: "checkEnvironment", status: "running" });
    child.emit("exit", 1, null);
    await rejected;
    runtime.stop();
    event({ operation: "checkEnvironment", status: "running" });
    expect(vi.getTimerCount()).toBe(0);
  });

  test("rejecting pending work clears its refreshed timers", async () => {
    const pending = new PendingRequests();
    const rejected = expect(pending.create("1", 1000, "checkEnvironment")).rejects.toThrow("write failed");
    const failed = expect(pending.create("2", 1000, "downloadChromeDriver")).rejects.toThrow("download failed");
    await vi.advanceTimersByTimeAsync(999);
    pending.refreshProgress("checkEnvironment");
    pending.refreshProgress("downloadChromeDriver");
    pending.reject("1", new Error("write failed"));
    pending.resolve({ type: "response", id: "2", ok: false, error: { message: "download failed" } });
    await Promise.all([rejected, failed]);
    pending.refreshProgress("checkEnvironment");
    pending.refreshProgress("downloadChromeDriver");
    expect(vi.getTimerCount()).toBe(0);
  });
});

describe("packaged runtime path", () => {
  const resources = path.join("/Apps", "RailWatch 12306.app", "Contents", "Resources");

  test("uses the onedir executable on both Windows and macOS", () => {
    expect(packagedRuntimeExecutable("C:/RailWatch/resources", "win32"))
      .toBe(path.join("C:/RailWatch/resources", "railwatch-runtime", "railwatch_runtime", "railwatch_runtime.exe"));
    expect(packagedRuntimeExecutable(resources, "darwin"))
      .toBe(path.join(resources, "railwatch-runtime", "railwatch_runtime", "railwatch_runtime"));
  });

  test("a packaged app with the runtime file starts it directly", () => {
    for (const [platform, resourcesPath, filename] of [
      ["win32", "C:/RailWatch/resources", "railwatch_runtime.exe"],
      ["darwin", resources, "railwatch_runtime"],
    ] as const) {
      const command = createPythonRuntimeCommand("/project", {
        isPackaged: true, resourcesPath, platform, fileExists: () => true,
      });
      const executable = path.join(resourcesPath, "railwatch-runtime", "railwatch_runtime", filename);
      expect(command).toEqual({ executable, args: [], cwd: path.dirname(executable) });
    }
  });

  test("a packaged app with a missing runtime never falls back to a system Python", () => {
    const command = createPythonRuntimeCommand("/project", {
      isPackaged: true, resourcesPath: resources, platform: "darwin", fileExists: () => false,
    });
    expect(command.missing).toBe(RUNTIME_MISSING_MESSAGE);
    expect(command.executable).not.toBe("python");
    expect(command.args).toEqual([]);
  });

  test("development runs the source runtime with Python", () => {
    const command = createPythonRuntimeCommand("/project", { isPackaged: false });
    expect(command.args).toEqual([path.join("/project", "railwatch_runtime.py")]);
    expect(command.missing).toBeUndefined();
  });
});
