// @vitest-environment jsdom
import { afterEach, beforeEach, expect, test, vi } from "vitest";

let startup: typeof import("./startupSplash");
let reducedMotion = false;

beforeEach(async () => {
  vi.resetModules();
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "performance"] });
  reducedMotion = false;
  vi.stubGlobal("railwatch", undefined);
  vi.stubGlobal("matchMedia", vi.fn((query: string) => ({
    matches: query === "(prefers-reduced-motion: reduce)" && reducedMotion,
    media: query,
  })));
  document.body.innerHTML = `
    <div id="startup-splash" role="status" aria-label="RailWatch 12306 正在启动"></div>
    <div id="root" inert></div>
  `;
  startup = await import("./startupSplash");
});

afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  document.body.replaceChildren();
});

test("the application stays inert while startup is still pending", () => {
  startup.initializeStartupSplash();

  vi.advanceTimersByTime(9999);

  expect(document.getElementById("root")?.hasAttribute("inert")).toBe(true);
  const splash = document.getElementById("startup-splash");
  expect(splash).not.toBeNull();
  expect(splash?.getAttribute("aria-hidden")).toBeNull();
  expect(splash?.classList.contains("startup-splash-leaving")).toBe(false);
});

test("a fast startup shows the logo for 1300ms before its 220ms fade", () => {
  startup.initializeStartupSplash();
  vi.advanceTimersByTime(100);
  startup.finishStartupSplash();

  vi.advanceTimersByTime(1199);
  expect(document.getElementById("root")?.hasAttribute("inert")).toBe(true);
  expect(document.getElementById("startup-splash")?.classList.contains("startup-splash-leaving")).toBe(false);

  vi.advanceTimersByTime(1);
  expect(document.getElementById("root")?.hasAttribute("inert")).toBe(false);
  const splash = document.getElementById("startup-splash");
  expect(splash?.getAttribute("aria-hidden")).toBe("true");
  expect(splash?.classList.contains("startup-splash-leaving")).toBe(true);

  vi.advanceTimersByTime(219);
  expect(document.getElementById("startup-splash")).toBe(splash);
  vi.advanceTimersByTime(1);
  expect(document.getElementById("startup-splash")).toBeNull();
  expect(vi.getTimerCount()).toBe(0);
});

test("repeated completion calls share one dismissal and do not restore timers", () => {
  startup.initializeStartupSplash();
  startup.finishStartupSplash();
  startup.finishStartupSplash();
  startup.finishStartupSplash();
  expect(vi.getTimerCount()).toBe(1);

  vi.advanceTimersByTime(1300);
  startup.finishStartupSplash();
  expect(vi.getTimerCount()).toBe(1);

  vi.advanceTimersByTime(220);
  startup.finishStartupSplash();
  expect(document.getElementById("startup-splash")).toBeNull();
  expect(document.getElementById("root")?.hasAttribute("inert")).toBe(false);
  expect(vi.getTimerCount()).toBe(0);
});

test("the ten-second fallback releases the application when initialization never settles", () => {
  startup.initializeStartupSplash();
  vi.advanceTimersByTime(9999);
  expect(document.getElementById("root")?.hasAttribute("inert")).toBe(true);

  // The fallback queues a zero-delay dismissal, which fake timers run on the next tick.
  vi.advanceTimersByTime(2);
  expect(document.getElementById("root")?.hasAttribute("inert")).toBe(false);
  expect(document.getElementById("startup-splash")?.classList.contains("startup-splash-leaving")).toBe(true);

  vi.advanceTimersByTime(220);
  expect(document.getElementById("startup-splash")).toBeNull();
  expect(vi.getTimerCount()).toBe(0);
});

test("reduced motion skips both the minimum display time and the fade delay", () => {
  reducedMotion = true;
  const startedAt = performance.now();
  startup.initializeStartupSplash();
  startup.finishStartupSplash();

  vi.runAllTimers();

  expect(performance.now() - startedAt).toBeLessThan(10);
  expect(document.getElementById("startup-splash")).toBeNull();
  expect(document.getElementById("root")?.hasAttribute("inert")).toBe(false);
  expect(vi.getTimerCount()).toBe(0);
});

test("hidden-window loading does not consume the drawing or minimum display time", async () => {
  let shown!: () => void;
  const whenShown = new Promise<void>((resolve) => { shown = resolve; });
  vi.stubGlobal("railwatch", { whenWindowShown: () => whenShown });
  startup.initializeStartupSplash();
  startup.finishStartupSplash();

  vi.advanceTimersByTime(2500);
  const splash = document.getElementById("startup-splash")!;
  expect(splash.classList.contains("startup-splash-running")).toBe(false);
  expect(document.getElementById("root")?.hasAttribute("inert")).toBe(true);

  shown();
  await whenShown;
  expect(splash.classList.contains("startup-splash-running")).toBe(true);
  vi.advanceTimersByTime(1299);
  expect(document.getElementById("root")?.hasAttribute("inert")).toBe(true);
  vi.advanceTimersByTime(1);
  expect(splash.classList.contains("startup-splash-leaving")).toBe(true);
  vi.advanceTimersByTime(220);
  expect(document.getElementById("startup-splash")).toBeNull();
  expect(vi.getTimerCount()).toBe(0);
});

test("an early window notification starts the animation when the renderer initializes", async () => {
  const whenShown = Promise.resolve();
  vi.stubGlobal("railwatch", { whenWindowShown: () => whenShown });
  startup.initializeStartupSplash();
  await whenShown;
  expect(document.getElementById("startup-splash")?.classList.contains("startup-splash-running")).toBe(true);

  vi.advanceTimersByTime(2000);
  startup.finishStartupSplash();
  vi.runAllTimers();
  expect(document.getElementById("startup-splash")).toBeNull();
  expect(vi.getTimerCount()).toBe(0);
});

test("a lost window notification cannot leave the application inaccessible", () => {
  vi.stubGlobal("railwatch", { whenWindowShown: () => new Promise<void>(() => {}) });
  startup.initializeStartupSplash();
  startup.finishStartupSplash();

  vi.runAllTimers();
  expect(document.getElementById("startup-splash")).toBeNull();
  expect(document.getElementById("root")?.hasAttribute("inert")).toBe(false);
  expect(vi.getTimerCount()).toBe(0);
});
