import { describe, expect, test } from "vitest";
import { JsonLineDecoder, PendingRequests, resolveRailWatchAppVersion } from "../pythonRuntime";

describe("resolveRailWatchAppVersion", () => {
  test("reads the app version from the project package.json", () => {
    expect(resolveRailWatchAppVersion()).toBe("0.1.0");
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
