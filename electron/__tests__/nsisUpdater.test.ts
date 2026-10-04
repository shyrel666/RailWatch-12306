import { EventEmitter } from "node:events";
import path from "node:path";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { launchProcess, RailWatchNsisUpdater } from "../nsisUpdater";

const mocks = vi.hoisted(() => ({ spawn: vi.fn() }));
vi.mock("node:child_process", async importOriginal => ({
  ...await importOriginal<typeof import("node:child_process")>(), spawn: mocks.spawn,
}));

let children: Array<EventEmitter & { unref: ReturnType<typeof vi.fn> }>;
beforeEach(() => {
  children = [];
  mocks.spawn.mockReset().mockImplementation(() => {
    const child = Object.assign(new EventEmitter(), { unref: vi.fn() });
    children.push(child);
    return child;
  });
  vi.stubGlobal("process", Object.assign(Object.create(process), { resourcesPath: "C:/RailWatch/resources" }));
});
afterEach(() => vi.unstubAllGlobals());

function updater(admin = false) {
  // Real upstream class/metadata interface; only OS process creation is mocked.
  const instance = new RailWatchNsisUpdater(null, {
    version: "0.5.3", name: "RailWatch", isPackaged: true, appUpdateConfigPath: "", userDataPath: "", baseCachePath: "",
    whenReady: async () => undefined, quit: vi.fn(), relaunch: vi.fn(), onQuit: vi.fn(),
  });
  Object.assign(instance, { downloadedUpdateHelper: {
    file: "C:/update cache/RailWatch.exe", packageFile: null,
    downloadedFileInfo: { fileName: "RailWatch.exe", sha512: "verified-by-upstream", isAdminRightsRequired: admin },
  } });
  return instance;
}

test("a ChildProcess return is not success until spawn is acknowledged", async () => {
  const pending = launchProcess("installer.exe", ["--updated"]);
  let settled = false;
  void pending.then(() => { settled = true; });
  await Promise.resolve();
  expect(settled).toBe(false);
  children[0].emit("spawn");
  await pending;
  expect(children[0].unref).toHaveBeenCalledOnce();
  expect(mocks.spawn).toHaveBeenCalledWith("installer.exe", ["--updated"], {
    detached: true, stdio: "ignore", windowsHide: true,
  });
});

test("asynchronous spawn failure is returned without requesting app quit", async () => {
  const instance = updater();
  const quit = vi.spyOn(instance, "quitAndInstall");
  const pending = instance.launchInstaller();
  const failed = expect(pending).rejects.toThrow("spawn failed");
  children[0].emit("error", Object.assign(new Error("spawn failed"), { code: "ENOENT" }));
  await failed;
  expect(quit).not.toHaveBeenCalled();
});

test("verified NSIS metadata supplies installer flags without invoking upstream auto-quit", async () => {
  const instance = updater();
  instance.installDirectory = "C:/RailWatch install";
  const quit = vi.spyOn(instance, "quitAndInstall");
  const pending = instance.launchInstaller();
  expect(mocks.spawn.mock.calls[0].slice(0, 2)).toEqual([
    "C:/update cache/RailWatch.exe", ["--updated", "--force-run", "/D=C:/RailWatch install"],
  ]);
  children[0].emit("spawn");
  await pending;
  expect(quit).not.toHaveBeenCalled();
});

test.each([0, 1])("elevation waits for helper exit and detects UAC cancellation (exit=%s)", async code => {
  const pending = updater(true).launchInstaller();
  const outcome = pending.then(() => "launched", error => error.message);
  let settled = false;
  void outcome.then(() => { settled = true; });
  children[0].emit("spawn");
  await Promise.resolve();
  expect(settled).toBe(false);
  expect(mocks.spawn.mock.calls[0][0]).toBe(path.join(process.resourcesPath, "elevate.exe"));
  children[0].emit("exit", code, null);
  expect(await outcome).toBe(code === 0 ? "launched" : "安装程序提权启动失败或已取消（1）。");
});

test("access denial falls back to elevation and waits for that launch", async () => {
  const pending = updater().launchInstaller();
  children[0].emit("error", Object.assign(new Error("denied"), { code: "EACCES" }));
  await new Promise(resolve => setImmediate(resolve));
  expect(children).toHaveLength(2);
  expect(mocks.spawn.mock.calls[1][1]).toEqual(["C:/update cache/RailWatch.exe", "--updated", "--force-run"]);
  children[1].emit("spawn");
  children[1].emit("exit", 0, null);
  await pending;
});
