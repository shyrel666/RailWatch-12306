import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, expect, test } from "vitest";
import {
  loadWindowState,
  resolveWindowLayout,
  saveWindowStateSync,
  themeBackgroundColor,
} from "../windowState";

let tempDir: string;

beforeEach(async () => {
  tempDir = await mkdtemp(path.join(os.tmpdir(), "railwatch-winstate-test-"));
});

afterEach(async () => {
  await rm(tempDir, { recursive: true, force: true });
});

test("scales initial window within compact laptop work areas while keeping defaults on large monitors", () => {
  const large = { x: 0, y: 0, width: 1920, height: 1040 };
  expect(resolveWindowLayout({}, [large], large)).toEqual({
    x: undefined,
    y: undefined,
    width: 1440,
    height: 900,
    minWidth: 840,
    minHeight: 580,
    maximized: false,
  });

  const laptop = { x: 0, y: 0, width: 1280, height: 680 };
  const compact = resolveWindowLayout({}, [laptop], laptop);
  expect(compact.width).toBeLessThanOrEqual(1280);
  expect(compact.height).toBeLessThanOrEqual(680);
  expect(compact.minWidth).toBe(840);
  expect(compact.minHeight).toBe(580);
});

test("clamps saved bounds back onto an active display when a secondary monitor disconnects", () => {
  const primary = { x: 0, y: 0, width: 1600, height: 900 };
  const disconnected = resolveWindowLayout(
    { x: 2500, y: 120, width: 1200, height: 800, maximized: true },
    [primary],
    primary,
  );
  expect(disconnected.x).toBe(400);
  expect(disconnected.y).toBe(100);
  expect(disconnected.width).toBe(1200);
  expect(disconnected.height).toBe(800);
  expect(disconnected.maximized).toBe(true);

  const secondary = { x: 1600, y: 0, width: 1920, height: 1080 };
  const restoredSecond = resolveWindowLayout(
    { x: 1700, y: 80, width: 1200, height: 800 },
    [primary, secondary],
    primary,
  );
  expect(restoredSecond.x).toBe(1700);
  expect(restoredSecond.y).toBe(80);
});

test("themeBackgroundColor matches light, dark and system appearance tokens", () => {
  expect(themeBackgroundColor("light", true)).toBe("#f4f3ef");
  expect(themeBackgroundColor("dark", false)).toBe("#101113");
  expect(themeBackgroundColor("system", false)).toBe("#f4f3ef");
  expect(themeBackgroundColor("system", true)).toBe("#101113");
});

test("persists and safely recovers corrupted window-state files", async () => {
  const filePath = path.join(tempDir, "nested", "window-state.json");
  saveWindowStateSync(filePath, { x: 120, y: 60, width: 1100, height: 760, maximized: false, theme: "light" });
  expect(loadWindowState(filePath)).toEqual({
    x: 120,
    y: 60,
    width: 1100,
    height: 760,
    maximized: false,
    theme: "light",
  });
  expect(JSON.parse(await readFile(filePath, "utf8")).theme).toBe("light");

  await writeFile(filePath, "{broken", "utf8");
  expect(loadWindowState(filePath)).toEqual({});
});
