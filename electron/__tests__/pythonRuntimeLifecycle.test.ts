import { EventEmitter } from "node:events";
import { PassThrough } from "node:stream";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

const { spawn, execFile } = vi.hoisted(() => ({ spawn: vi.fn(), execFile: vi.fn() }));
vi.mock("node:child_process", () => ({ spawn, execFile }));
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
    execFile.mockReset();
    client = new RailWatchPythonRuntimeClient({ executable: "python", args: [], cwd: process.cwd() });
  });
  afterEach(() => {
    client.stop();
    vi.unstubAllGlobals();
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
    expect(restarted).not.toHaveBeenCalled();
    second.stdout.write('{"type":"response","id":"2","ok":true,"result":{"state":{}}}\n');
    await vi.advanceTimersByTimeAsync(0);
    expect(restarted).toHaveBeenCalledOnce();
    const result = client.request("loadConfig");
    second.stdout.write('{"type":"response","id":"3","ok":true,"result":42}\n');
    await expect(result).resolves.toBe(42);
  });

  test("old exit and output cannot corrupt a replacement process", async () => {
    const first = child(), second = child();
    spawn.mockReturnValueOnce(first).mockReturnValueOnce(second);
    client.start();
    first.stdout.write('{"type":');
    first.emit("error", new Error("failed"));
    client.retry();
    const result = client.request("loadConfig");
    first.emit("exit", 1, null);
    first.stdout.write('{"type":"response","id":"1","ok":true,"result":"stale"}\n');
    second.stdout.write('{"type":"response","id":"1","ok":true,"result":"fresh"}\n');
    await expect(result).resolves.toBe("fresh");
    expect(spawn).toHaveBeenCalledTimes(2);
  });

  test("slow startup can become ready without killing a healthy runtime", async () => {
    const first = child();
    spawn.mockReturnValue(first);
    const ready = vi.fn();
    client.on("ready", ready);
    client.start();
    first.emit("spawn");
    await vi.advanceTimersByTimeAsync(15000);
    expect(first.kill).not.toHaveBeenCalled();
    first.stdout.write('{"type":"response","id":"1","ok":true,"result":{"state":{}}}\n');
    await vi.advanceTimersByTimeAsync(20000);
    expect(ready).toHaveBeenCalledOnce();
    expect(first.kill).not.toHaveBeenCalled();
    expect(spawn).toHaveBeenCalledOnce();
  });

  test("a runtime that never becomes ready still times out and restarts", async () => {
    const first = child(), second = child();
    spawn.mockReturnValueOnce(first).mockReturnValueOnce(second);
    client.start();
    first.emit("spawn");
    await vi.advanceTimersByTimeAsync(30000);
    expect(first.kill).toHaveBeenCalledOnce();
    await vi.advanceTimersByTimeAsync(1000);
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

  test("repeated failures back off, stop after five retries, and require explicit retry", async () => {
    const children: ReturnType<typeof child>[] = [];
    spawn.mockImplementation(() => { const next = child(); children.push(next); return next; });
    const unavailable = vi.fn();
    client.on("unavailable", unavailable);
    client.start();
    for (let index = 0; index < 5; index++) {
      children[index].emit("error", new Error("ENOENT"));
      await expect(client.request("getRuntimeInfo")).rejects.toThrow("等待恢复");
      vi.advanceTimersByTime(1000 * 2 ** index - 1);
      expect(spawn).toHaveBeenCalledTimes(index + 1);
      vi.advanceTimersByTime(1);
    }
    children[5].emit("error", new Error("ENOENT"));
    vi.advanceTimersByTime(120000);
    expect(spawn).toHaveBeenCalledTimes(6);
    expect(unavailable).toHaveBeenCalledOnce();
    await expect(client.request("getRuntimeInfo")).rejects.toThrow("重试运行时");
    client.retry();
    expect(spawn).toHaveBeenCalledTimes(7);
  });

  test("force exit terminates only the owned Windows process tree and blocks new requests", async () => {
    vi.stubGlobal("process", Object.create(process, { platform: { value: "win32" } }));
    const first = Object.assign(child(), { pid: 12345 });
    spawn.mockReturnValue(first);
    let terminate!: (error: Error | null) => void;
    execFile.mockImplementation((_file, _args, _options, callback) => { terminate = callback; });
    const pending = expect(client.request("loadConfig")).rejects.toThrow("stopped");
    const stopped = client.forceStop();
    await pending;
    expect(execFile).toHaveBeenCalledWith("taskkill", ["/PID", "12345", "/T", "/F"],
      { windowsHide: true, timeout: 5000 }, expect.any(Function));
    expect(first.kill).not.toHaveBeenCalled();
    await expect(client.request("getRuntimeInfo")).rejects.toThrow("shutting down");
    terminate(null);
    await stopped;
    first.emit("exit", 1, null);
    vi.advanceTimersByTime(2000);
    expect(spawn).toHaveBeenCalledOnce();
  });

  test("failed or timed-out tree cleanup still terminates the owned runtime", async () => {
    vi.stubGlobal("process", Object.create(process, { platform: { value: "win32" } }));
    const first = Object.assign(child(), { pid: 12345 });
    spawn.mockReturnValue(first);
    execFile.mockImplementation((_file, _args, _options, callback) => callback(new Error("timeout")));
    client.start();
    await client.forceStop();
    expect(first.kill).toHaveBeenCalledOnce();
    expect(() => client.start()).toThrow("shutting down");
  });

  test("force exit after a crash cancels restart without targeting a stale PID", async () => {
    const first = Object.assign(child(), { pid: 12345 });
    spawn.mockReturnValue(first);
    client.start();
    first.emit("exit", 1, null);
    await client.forceStop();
    vi.advanceTimersByTime(2000);
    expect(spawn).toHaveBeenCalledOnce();
    expect(execFile).not.toHaveBeenCalled();
    await expect(client.request("loadConfig")).rejects.toThrow("shutting down");
  });

  test("non-Windows force exit kills the owned runtime without a Windows utility", async () => {
    vi.stubGlobal("process", Object.create(process, { platform: { value: "linux" } }));
    const first = child();
    spawn.mockReturnValue(first);
    client.start();
    await client.forceStop();
    expect(first.kill).toHaveBeenCalledWith("SIGKILL");
    expect(execFile).not.toHaveBeenCalled();
  });
});
