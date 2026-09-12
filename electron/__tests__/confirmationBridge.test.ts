import { describe, expect, test, vi } from "vitest";
import { ConfirmationBridge } from "../confirmationBridge";

describe("ConfirmationBridge", () => {
  test("sends the request to the renderer and resolves with the response", async () => {
    const sent: { id: string; title: string; message: string }[] = [];
    const bridge = new ConfirmationBridge({
      sendRequest: (request) => sent.push(request),
    });

    const promise = bridge.request({ title: "清除本地数据", message: "是否继续？" });
    expect(sent).toHaveLength(1);
    expect(sent[0].title).toBe("清除本地数据");

    bridge.respond(sent[0].id, true);
    await expect(promise).resolves.toBe(true);
  });

  test("treats any response other than true as declined", async () => {
    const sent: { id: string }[] = [];
    const bridge = new ConfirmationBridge({ sendRequest: (request) => sent.push(request) });

    const promise = bridge.request({ title: "t", message: "m" });
    bridge.respond(sent[0].id, false);
    await expect(promise).resolves.toBe(false);
  });

  test("declines automatically when the renderer never answers", async () => {
    vi.useFakeTimers();
    try {
      const bridge = new ConfirmationBridge({
        sendRequest: () => undefined,
        timeoutMs: 30_000,
      });
      const promise = bridge.request({ title: "t", message: "m" });
      const settled = vi.fn();
      void promise.then(settled);

      await vi.advanceTimersByTimeAsync(29_999);
      expect(settled).not.toHaveBeenCalled();
      await vi.advanceTimersByTimeAsync(1);
      expect(settled).toHaveBeenCalledWith(false);
    } finally {
      vi.useRealTimers();
    }
  });

  test("declines pending confirmations when the renderer window goes away", async () => {
    const bridge = new ConfirmationBridge({ sendRequest: () => undefined });
    const first = bridge.request({ title: "t1", message: "m1" });
    const second = bridge.request({ title: "t2", message: "m2" });

    bridge.cancelAll();
    await expect(first).resolves.toBe(false);
    await expect(second).resolves.toBe(false);
  });

  test("ignores unknown or duplicate responses", async () => {
    const sent: { id: string }[] = [];
    const bridge = new ConfirmationBridge({ sendRequest: (request) => sent.push(request) });

    bridge.respond("does-not-exist", true);

    const promise = bridge.request({ title: "t", message: "m" });
    bridge.respond(sent[0].id, true);
    bridge.respond(sent[0].id, false);
    await expect(promise).resolves.toBe(true);
  });

  test("declines when the request cannot be delivered to the renderer", async () => {
    const bridge = new ConfirmationBridge({
      sendRequest: () => {
        throw new Error("Renderer window is not available.");
      },
    });

    await expect(bridge.request({ title: "t", message: "m" })).resolves.toBe(false);
  });
});
