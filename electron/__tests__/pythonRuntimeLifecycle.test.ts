import { EventEmitter } from "node:events";
import { PassThrough } from "node:stream";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

const { spawn } = vi.hoisted(() => ({ spawn: vi.fn() }));
vi.mock("node:child_process", () => ({ spawn }));
vi.mock("electron", () => ({ app: { isPackaged: false, getAppPath: () => process.cwd() } }));
import { RailWatchPythonRuntimeClient } from "../pythonRuntime";

function child() {
  return Object.assign(new EventEmitter(), {
    stdout: new PassThrough(), stderr: new PassThrough(), stdin: new PassThrough(), kill: vi.fn(),
  });
}

describe("Python runtime lifecycle", () => {
  let client: RailWatchPythonRuntimeClient;
  beforeEach(() => {
    vi.useFakeTimers();
    spawn.mockReset();
    client = new RailWatchPythonRuntimeClient({ executable: "python", args: [], cwd: process.cwd() });
  });
  afterEach(() => {
    client.stop();
    vi.useRealTimers();
  });

  test("failed spawn retries without waiting for an exit event", async () => {
    const first = child(), second = child();
    spawn.mockReturnValueOnce(first).mockReturnValueOnce(second);
    const restarted = vi.fn();
    client.on("restarted", restarted);
    const rejected = expect(client.request("loadConfig")).rejects.toThrow("ENOENT");
    first.emit("error", new Error("ENOENT"));
    await rejected;
    vi.advanceTimersByTime(1000);
    expect(spawn).toHaveBeenCalledTimes(2);
    expect(restarted).not.toHaveBeenCalled();
    second.emit("spawn");
    expect(restarted).toHaveBeenCalledOnce();
    const result = client.request("loadConfig");
    second.stdout.write('{"type":"response","id":"2","ok":true,"result":42}\n');
    await expect(result).resolves.toBe(42);
  });

  test("old exit and output cannot corrupt a replacement process", async () => {
    const first = child(), second = child();
    spawn.mockReturnValueOnce(first).mockReturnValueOnce(second);
    client.start();
    first.stdout.write('{"type":');
    first.emit("error", new Error("failed"));
    client.start();
    const result = client.request("loadConfig");
    first.emit("exit", 1, null);
    first.stdout.write('{"type":"response","id":"1","ok":true,"result":"stale"}\n');
    second.stdout.write('{"type":"response","id":"1","ok":true,"result":"fresh"}\n');
    await expect(result).resolves.toBe("fresh");
    expect(spawn).toHaveBeenCalledTimes(2);
  });

  test("stopping rejects pending work and cancels scheduled restart", async () => {
    const first = child();
    spawn.mockReturnValue(first);
    const rejected = expect(client.request("loadConfig")).rejects.toThrow("stopped");
    client.stop();
    first.emit("exit", 0, null);
    vi.advanceTimersByTime(2000);
    await rejected;
    expect(spawn).toHaveBeenCalledOnce();
    expect(first.kill).toHaveBeenCalledOnce();
  });
});
