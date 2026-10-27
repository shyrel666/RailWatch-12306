import { spawn } from "node:child_process";
import path from "node:path";
import { NsisUpdater } from "electron-updater";
import { INSTALLER_UNAVAILABLE } from "./updateManager";

/** Resolve on OS launch acknowledgement, not merely a returned ChildProcess. */
export function launchProcess(executable: string, args: string[]): Promise<void> {
  return new Promise((resolve, reject) => {
    // windowsHide also hides NSIS's installer UI until a second launch restores it.
    const child = spawn(executable, args, { detached: true, stdio: "ignore", windowsHide: false });
    child.once("error", reject);
    child.once("spawn", () => {
      child.unref();
      resolve();
    });
  });
}

/** Quote like libuv so an elevated installer receives the same argv as a direct launch. */
export function windowsCommandLine(args: string[]): string {
  return args.map(arg => {
    if (!arg) return '""';
    if (!/[ \t"]/.test(arg)) return arg;
    return `"${arg.replace(/(\\*)"/g, '$1$1\\"').replace(/(\\+)$/, "$1$1")}"`;
  }).join(" ");
}

// The bundled elevate.exe hard-codes SW_HIDE for the program it starts, which hides
// NSIS's interactive UI. Process.Start keeps the normal window state, and the values
// arrive through the environment so no path is ever parsed as script.
const ELEVATE_SCRIPT = [
  "$ErrorActionPreference = 'Stop';",
  "try {",
  "$info = New-Object System.Diagnostics.ProcessStartInfo;",
  "$info.FileName = $env:RAILWATCH_ELEVATE_FILE;",
  "$info.Arguments = $env:RAILWATCH_ELEVATE_ARGS;",
  "$info.Verb = 'runas';",
  "$info.UseShellExecute = $true;",
  "[void][System.Diagnostics.Process]::Start($info);",
  "exit 0",
  "} catch {",
  // Unwrap PowerShell's MethodInvocationException so a declined UAC prompt exits 1223.
  "$e = $_.Exception;",
  "while ($e -and $e -isnot [System.ComponentModel.Win32Exception]) { $e = $e.InnerException };",
  "if ($e) { exit $e.NativeErrorCode };",
  "exit 1",
  "}",
].join(" ");

/** Resolve only after UAC is accepted and Windows has created the installer. */
export function launchElevated(executable: string, args: string[]): Promise<void> {
  const powershell = path.join(process.env.SystemRoot || "C:\\Windows", "System32", "WindowsPowerShell", "v1.0", "powershell.exe");
  return new Promise((resolve, reject) => {
    // Never detached: under DETACHED_PROCESS powershell.exe exits 0 without running the command.
    const child = spawn(powershell, ["-NoLogo", "-NoProfile", "-NonInteractive", "-Command", ELEVATE_SCRIPT], {
      stdio: "ignore", windowsHide: true,
      env: { ...process.env, RAILWATCH_ELEVATE_FILE: executable, RAILWATCH_ELEVATE_ARGS: windowsCommandLine(args) },
    });
    child.once("error", reject);
    // PowerShell exits once ShellExecute returns; its own spawn event cannot
    // prove UAC was accepted or the installer opened.
    child.once("exit", (code, signal) => {
      if (code === 0) resolve();
      else reject(new Error(`安装程序提权启动失败或已取消（${code ?? signal ?? "未知错误"}）。`));
    });
  });
}

/** Keep upstream download/signature checks; leave quitting to the main process. */
export class RailWatchNsisUpdater extends NsisUpdater {
  async launchInstaller(): Promise<void> {
    const installer = this.installerPath;
    const helper = this.downloadedUpdateHelper;
    if (!installer || !helper?.downloadedFileInfo) {
      throw Object.assign(new Error("已下载的安装程序不可用，请重新检查更新。"), { code: INSTALLER_UNAVAILABLE });
    }
    const args = ["--updated"];
    if (this.autoRunAppAfterInstall) args.push("--force-run");
    if (this.installDirectory) args.push(`/D=${this.installDirectory}`);
    if (helper.packageFile) args.push(`--package-file=${helper.packageFile}`);
    if (helper.downloadedFileInfo.isAdminRightsRequired) {
      await launchElevated(installer, args);
      return;
    }
    try {
      await launchProcess(installer, args);
    } catch (error) {
      const code = (error as NodeJS.ErrnoException).code;
      if (code !== "EACCES" && code !== "UNKNOWN") throw error;
      await launchElevated(installer, args);
    }
  }
}
