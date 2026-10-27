import { EventEmitter } from "node:events";
import path from "node:path";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { launchElevated, launchProcess, RailWatchNsisUpdater, windowsCommandLine } from "../nsisUpdater";
import { INSTALLER_UNAVAILABLE } from "../updateManager";

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
  vi.stubGlobal("process", Object.assign(Object.create(process), {
    resourcesPath: "C:/RailWatch/resources", env: { ...process.env, SystemRoot: "C:\\Windows" },
  }));
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
    detached: true, stdio: "ignore", windowsHide: false,
  });
});

test("a vanished download is reported with the code that sends users back to checking", async () => {
  const instance = updater();
  Object.assign(instance, { downloadedUpdateHelper: null });
  await expect(instance.launchInstaller()).rejects.toMatchObject({ code: INSTALLER_UNAVAILABLE });
  expect(mocks.spawn).not.toHaveBeenCalled();
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
  expect(mocks.spawn).toHaveBeenCalledWith(
    "C:/update cache/RailWatch.exe", ["--updated", "--force-run", "/D=C:/RailWatch install"],
    { detached: true, stdio: "ignore", windowsHide: false },
  );
  children[0].emit("spawn");
  await pending;
  expect(quit).not.toHaveBeenCalled();
});

const powershell = path.join("C:\\Windows", "System32", "WindowsPowerShell", "v1.0", "powershell.exe");

function expectElevated(call: unknown[], installer: string, commandLine: string) {
  const [executable, args, options] = call as [string, string[], { env: NodeJS.ProcessEnv }];
  expect(executable).toBe(powershell);
  expect(args.slice(0, 4)).toEqual(["-NoLogo", "-NoProfile", "-NonInteractive", "-Command"]);
  // Paths travel only through the environment, never inside the script text.
  expect(args[4]).toContain("$info.Verb = 'runas'");
  expect(args[4]).not.toContain(installer);
  expect(options).toMatchObject({ stdio: "ignore", windowsHide: true });
  // A detached powershell.exe exits 0 without running the script, faking UAC success.
  expect(options).not.toHaveProperty("detached");
  expect(options.env).toMatchObject({ RAILWATCH_ELEVATE_FILE: installer, RAILWATCH_ELEVATE_ARGS: commandLine });
}

test.each([0, 1223])("elevation waits for helper exit and detects UAC cancellation (exit=%s)", async code => {
  const pending = updater(true).launchInstaller();
  const outcome = pending.then(() => "launched", error => error.message);
  let settled = false;
  void outcome.then(() => { settled = true; });
  children[0].emit("spawn");
  await Promise.resolve();
  expect(settled).toBe(false);
  expect(mocks.spawn).toHaveBeenCalledOnce();
  expectElevated(mocks.spawn.mock.calls[0], "C:/update cache/RailWatch.exe", "--updated --force-run");
  children[0].emit("exit", code, null);
  expect(await outcome).toBe(code === 0 ? "launched" : "安装程序提权启动失败或已取消（1223）。");
});

test("a PowerShell launch failure is reported instead of waiting for an exit", async () => {
  const pending = launchElevated("C:/update cache/RailWatch.exe", ["--updated"]);
  children[0].emit("error", Object.assign(new Error("missing"), { code: "ENOENT" }));
  await expect(pending).rejects.toMatchObject({ code: "ENOENT" });
});

test("access denial falls back to elevation and waits for that launch", async () => {
  const instance = updater();
  instance.installDirectory = "C:/RailWatch install";
  const pending = instance.launchInstaller();
  children[0].emit("error", Object.assign(new Error("denied"), { code: "EACCES" }));
  await new Promise(resolve => setImmediate(resolve));
  expect(children).toHaveLength(2);
  expect(mocks.spawn).toHaveBeenNthCalledWith(1,
    "C:/update cache/RailWatch.exe", ["--updated", "--force-run", "/D=C:/RailWatch install"],
    { detached: true, stdio: "ignore", windowsHide: false },
  );
  expectElevated(mocks.spawn.mock.calls[1], "C:/update cache/RailWatch.exe", '--updated --force-run "/D=C:/RailWatch install"');
  children[1].emit("spawn");
  children[1].emit("exit", 0, null);
  await pending;
});

test("elevated arguments are quoted exactly as a direct launch would pass them", () => {
  expect(windowsCommandLine(["--updated", "", "a b", 'say "hi"', "C:\\dir with space\\", 'x\\"y', "C:\\plain\\"]))
    .toBe('--updated "" "a b" "say \\"hi\\"" "C:\\dir with space\\\\" "x\\\\\\"y" C:\\plain\\');
});
