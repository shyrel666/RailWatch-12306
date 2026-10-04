import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, test } from "vitest";
import {
  JsonLineDecoder,
  PendingRequests,
  RUNTIME_MISSING_MESSAGE,
  createPythonRuntimeCommand,
  packagedRuntimeExecutable,
  resolveRailWatchAppVersion,
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

describe("packaged runtime path", () => {
  const resources = path.join("/Apps", "RailWatch 12306.app", "Contents", "Resources");

  test("uses the onefile exe on Windows and the onedir executable elsewhere", () => {
    expect(packagedRuntimeExecutable("C:/RailWatch/resources", "win32"))
      .toBe(path.join("C:/RailWatch/resources", "railwatch-runtime", "railwatch_runtime.exe"));
    expect(packagedRuntimeExecutable(resources, "darwin"))
      .toBe(path.join(resources, "railwatch-runtime", "railwatch_runtime", "railwatch_runtime"));
  });

  test("a packaged app with the runtime file starts it directly", () => {
    const command = createPythonRuntimeCommand("/project", {
      isPackaged: true, resourcesPath: resources, platform: "darwin", fileExists: () => true,
    });
    const executable = path.join(resources, "railwatch-runtime", "railwatch_runtime", "railwatch_runtime");
    expect(command).toEqual({ executable, args: [], cwd: path.dirname(executable) });
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
