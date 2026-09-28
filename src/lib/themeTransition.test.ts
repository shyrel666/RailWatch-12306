// @vitest-environment jsdom
import { afterEach, expect, test, vi } from "vitest";
import { transitionTheme } from "./themeTransition";

afterEach(() => {
  vi.restoreAllMocks();
  Reflect.deleteProperty(document, "startViewTransition");
  Reflect.deleteProperty(document.documentElement, "animate");
  delete document.documentElement.dataset.themeTransition;
});

function nativeTransition() {
  vi.spyOn(window, "matchMedia").mockReturnValue({ matches: false } as MediaQueryList);
  const transition = { ready: Promise.resolve(), finished: Promise.resolve(), updateCallbackDone: Promise.resolve(), skipTransition: vi.fn() };
  const start = vi.fn((update: () => void) => { update(); return transition; });
  Object.defineProperty(document, "startViewTransition", { configurable: true, value: start, writable: true });
  Object.defineProperty(document.documentElement, "animate", { configurable: true, value: () => {}, writable: true });
  const cancel = vi.fn();
  const animate = vi.spyOn(document.documentElement, "animate").mockReturnValue({ finished: Promise.resolve(), cancel } as unknown as Animation);
  return { transition, start, animate, cancel };
}

test("reveals one snapshot from the button and cleans up animation state", async () => {
  const { start, animate, cancel } = nativeTransition();
  const update = vi.fn();
  await transitionTheme(update, { x: 100, y: 50 });
  expect(start).toHaveBeenCalledTimes(1);
  expect(update).toHaveBeenCalledTimes(1);
  expect(animate).toHaveBeenCalledWith({ clipPath: ["circle(0px at 100px 50px)", expect.stringContaining("at 100px 50px)")] },
    expect.objectContaining({ duration: 420, pseudoElement: "::view-transition-new(root)" }));
  expect(cancel).toHaveBeenCalledTimes(1);
  expect(document.documentElement.dataset.themeTransition).toBeUndefined();
});

test("reduced motion applies directly without a transition", async () => {
  const { start } = nativeTransition();
  vi.spyOn(window, "matchMedia").mockReturnValue({ matches: true } as MediaQueryList);
  const update = vi.fn();
  await transitionTheme(update);
  expect(start).not.toHaveBeenCalled();
  expect(update).toHaveBeenCalledTimes(1);
});

test("snapshot rejection does not block applying the theme or double apply", async () => {
  const { transition } = nativeTransition();
  transition.ready = Promise.reject(new Error("hidden"));
  const update = vi.fn();
  await transitionTheme(update);
  expect(update).toHaveBeenCalledTimes(1);
  expect(transition.skipTransition).toHaveBeenCalledTimes(1);
  expect(document.documentElement.dataset.themeTransition).toBeUndefined();
});

test("a native API failure before the callback still applies the theme", async () => {
  const { start } = nativeTransition();
  start.mockImplementation(() => { throw new Error("unavailable"); });
  const update = vi.fn();
  await transitionTheme(update);
  expect(update).toHaveBeenCalledTimes(1);
});
