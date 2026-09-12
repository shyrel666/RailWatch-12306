// @vitest-environment jsdom
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { railwatchApi } from "./railwatchApi";
import { useThemePreference } from "./useThemePreference";

let systemDark = false;
let listener: (() => void) | undefined;
beforeEach(() => {
  localStorage.clear();
  systemDark = false;
  vi.spyOn(window, "matchMedia").mockImplementation(
    () =>
      ({
        get matches() {
          return systemDark;
        },
        addEventListener: (_: string, callback: () => void) => {
          listener = callback;
        },
        removeEventListener: vi.fn(),
      }) as unknown as MediaQueryList,
  );
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

test("follows system changes only in system mode and applies tokens to document root", async () => {
  vi.spyOn(railwatchApi, "command").mockImplementation(
    async (command, payload) =>
      ({
        theme: command === "loadPreferences" ? "system" : payload?.theme,
      }) as never,
  );
  const { result } = renderHook(useThemePreference);
  await waitFor(() => expect(result.current.disabled).toBe(false));
  act(() => {
    systemDark = true;
    listener?.();
  });
  expect(result.current.darkMode).toBe(true);
  expect(document.documentElement.dataset.theme).toBe("dark");
  expect(document.documentElement.style.getPropertyValue("--surface")).toBe(
    "#202622",
  );
  await act(() => result.current.saveTheme("light"));
  act(() => {
    systemDark = false;
    listener?.();
    systemDark = true;
    listener?.();
  });
  expect(result.current.darkMode).toBe(false);
  expect(localStorage.getItem("railwatch.theme")).toBe("light");
  await act(() => result.current.saveTheme("system"));
  expect(result.current.darkMode).toBe(true);
});
test.each(["light", "dark"])(
  "loads existing %s preference without replacing it",
  async (mode) => {
    vi.spyOn(railwatchApi, "command").mockResolvedValue({ theme: mode });
    const { result } = renderHook(useThemePreference);
    await waitFor(() => expect(result.current.mode).toBe(mode));
    expect(railwatchApi.command).toHaveBeenCalledTimes(1);
  },
);
test("restores previous theme after save failure", async () => {
  const command = vi
    .spyOn(railwatchApi, "command")
    .mockResolvedValueOnce({ theme: "dark" })
    .mockRejectedValueOnce(new Error("磁盘不可写"));
  const { result } = renderHook(useThemePreference);
  await waitFor(() => expect(result.current.disabled).toBe(false));
  await act(async () => {
    await expect(result.current.saveTheme("light")).rejects.toThrow(
      "磁盘不可写",
    );
  });
  expect(result.current.mode).toBe("dark");
  expect(document.documentElement.dataset.theme).toBe("dark");
  expect(localStorage.getItem("railwatch.theme")).toBe("dark");
  expect(command).toHaveBeenLastCalledWith("savePreferences", {
    theme: "light",
  });
});
test("ignores duplicate saves while a theme request is pending", async () => {
  let complete!: (value: unknown) => void;
  const command = vi
    .spyOn(railwatchApi, "command")
    .mockResolvedValueOnce({ theme: "system" })
    .mockImplementation(
      () =>
        new Promise((resolve) => {
          complete = resolve;
        }) as never,
    );
  const { result } = renderHook(useThemePreference);
  await waitFor(() => expect(result.current.disabled).toBe(false));
  let pending!: Promise<void>;
  act(() => {
    pending = result.current.saveTheme("dark");
  });
  await act(() => result.current.saveTheme("light"));
  expect(command).toHaveBeenCalledTimes(2);
  await act(async () => {
    complete({ theme: "dark" });
    await pending;
  });
  expect(result.current.mode).toBe("dark");
});
