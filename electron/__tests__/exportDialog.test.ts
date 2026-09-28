import { afterEach, beforeEach, expect, test } from "vitest";
import { mkdtemp, mkdir, writeFile, readFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { listExportDirectory, validateLogExport } from "../exportDialog";

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
