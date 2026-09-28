// @vitest-environment jsdom
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { useSidebarPreference } from "./useSidebarPreference";

let compact = false;
let resize: () => void;
beforeEach(() => {
  localStorage.clear();
  compact = false;
  vi.spyOn(window, "matchMedia").mockImplementation(() => ({
    get matches() { return compact; },
    addEventListener: (_: string, listener: () => void) => { resize = listener; },
    removeEventListener: vi.fn(),
  }) as unknown as MediaQueryList);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

test("remembers collapse and expansion after remount", () => {
  const first = renderHook(useSidebarPreference);
  act(() => first.result.current.toggle());
  expect(first.result.current.collapsed).toBe(true);
  first.unmount();
  const second = renderHook(useSidebarPreference);
  expect(second.result.current.collapsed).toBe(true);
  act(() => second.result.current.toggle());
  second.unmount();
  compact = true;
  const third = renderHook(useSidebarPreference);
  expect(third.result.current.collapsed).toBe(false);
});

test("adapts to width only until the user explicitly chooses", () => {
  const { result } = renderHook(useSidebarPreference);
  act(() => { compact = true; resize(); });
  expect(result.current.collapsed).toBe(true);
  act(() => result.current.toggle());
  act(() => { compact = false; resize(); });
  act(() => { compact = true; resize(); });
  expect(result.current.collapsed).toBe(false);
});

test("storage failure still allows manual toggle", () => {
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("full"); });
  const { result } = renderHook(useSidebarPreference);
  act(() => result.current.toggle());
  expect(result.current.collapsed).toBe(true);
});
