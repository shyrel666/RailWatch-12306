import { afterEach, beforeEach, expect, test } from "vitest";
import { mkdtemp, mkdir, writeFile, readFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { listExportDirectory, listExportRoots, normalizeExportPathInput, validateLogExport } from "../exportDialog";

let directory: string;
beforeEach(async () => { directory = await mkdtemp(path.join(os.tmpdir(), "railwatch-export-test-")); });
afterEach(async () => { await rm(directory, { recursive: true, force: true }); });

test("lists folders and text filenames without reading file contents", async () => {
  await mkdir(path.join(directory, "行程"));
  await writeFile(path.join(directory, "events.txt"), "existing log");
  await writeFile(path.join(directory, "settings.json"), "{}");
  expect(await listExportDirectory(directory)).toEqual({ directory, parent: path.dirname(directory),
    folders: [{ name: "行程", path: path.join(directory, "行程") }], files: ["events.txt"] });
});

test("detects overwrite without changing existing data and appends the text extension", async () => {
  await writeFile(path.join(directory, "events.txt"), "keep me");
  expect(await validateLogExport(directory, "events")).toEqual({ filePath: path.join(directory, "events.txt"), exists: true });
  expect(await readFile(path.join(directory, "events.txt"), "utf8")).toBe("keep me");
  expect((await validateLogExport(directory, "new.txt")).exists).toBe(false);
});

test.each(["../outside", "..\\outside", "CON.txt", "report:stream", "bad/child", "name.", "", "nul", "name "])(
  "rejects unsafe filenames: %s", async name => {
    await expect(validateLogExport(directory, name)).rejects.toThrow();
  },
);
test("rejects relative locations and folders in place of output files", async () => {
  await expect(listExportDirectory("relative")).rejects.toThrow();
  await expect(validateLogExport("relative", "events")).rejects.toThrow();
  await mkdir(path.join(directory, "events.txt"));
  await expect(validateLogExport(directory, "events")).rejects.toThrow();
});
test("normalizes bare Windows drive letters and probes cross-platform export roots", async () => {
  expect(normalizeExportPathInput(" d: ", "win32")).toBe("D:\\");
  expect(normalizeExportPathInput("d:/logs", "win32")).toBe("d:/logs");
  expect(normalizeExportPathInput("/Volumes/USB", "darwin")).toBe("/Volumes/USB");

  const winRoots = await listExportRoots({
    platform: "win32",
    accessFn: async (target) => {
      if (target !== "C:\\" && target !== "D:\\") throw new Error("ENOENT");
    },
  });
  expect(winRoots).toEqual([
    { name: "C:\\", path: "C:\\" },
    { name: "D:\\", path: "D:\\" },
  ]);

  const macRoots = await listExportRoots({
    platform: "darwin",
    homeDir: "/Users/alice",
    readdirFn: async () => [
      { name: ".Spotlight-V100", isDirectory: () => true } as any,
      { name: "Macintosh HD", isDirectory: () => true } as any,
      { name: "USB Drive", isDirectory: () => true } as any,
      { name: "README.txt", isDirectory: () => false } as any,
    ],
  });
  expect(macRoots).toEqual([
    { name: "根目录 /", path: "/" },
    { name: "主目录", path: "/Users/alice" },
    { name: "Macintosh HD", path: "/Volumes/Macintosh HD" },
    { name: "USB Drive", path: "/Volumes/USB Drive" },
  ]);
});

test("times out slow or disconnected Windows drive probes instead of stalling", async () => {
  const winRoots = await listExportRoots({
    platform: "win32",
    timeoutMs: 20,
    accessFn: async (target) => {
      if (target === "Z:\\") {
        await new Promise<void>(() => {});
      }
      if (target !== "C:\\" && target !== "D:\\") {
        throw new Error("ENOENT");
      }
    },
  });
  expect(winRoots).toEqual([
    { name: "C:\\", path: "C:\\" },
    { name: "D:\\", path: "D:\\" },
  ]);
});

test("a drive whose probe has not settled is not probed again until it does", async () => {
  const calls: string[] = [];
  let hangZ = true;
  let releaseZ!: () => void;
  const accessFn = async (target: string) => {
    calls.push(target);
    if (target === "Z:\\") {
      if (hangZ) await new Promise<void>((resolve) => { releaseZ = resolve; });
      return;
    }
    if (target !== "C:\\") throw new Error("ENOENT");
  };
  const probe = () => listExportRoots({ platform: "win32", timeoutMs: 20, accessFn });
  const count = (drive: string) => calls.filter((target) => target === drive).length;
  const onlyC = [{ name: "C:\\", path: "C:\\" }];

  expect(await probe()).toEqual(onlyC);
  expect(await probe()).toEqual(onlyC);
  // The hung probe is shared; drives that answered are probed afresh.
  expect(count("Z:\\")).toBe(1);
  expect(count("C:\\")).toBe(2);

  hangZ = false;
  releaseZ();
  await new Promise((resolve) => setTimeout(resolve, 0));
  expect(await probe()).toEqual([...onlyC, { name: "Z:\\", path: "Z:\\" }]);
  expect(count("Z:\\")).toBe(2);
});
