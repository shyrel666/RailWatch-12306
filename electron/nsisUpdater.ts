import { spawn } from "node:child_process";
import path from "node:path";
import { NsisUpdater } from "electron-updater";

/** Resolve on OS launch acknowledgement, not merely a returned ChildProcess. */
export function launchProcess(executable: string, args: string[], elevated = false): Promise<void> {
  return new Promise((resolve, reject) => {
    const child = spawn(executable, args, { detached: true, stdio: "ignore", windowsHide: true });
    child.once("error", reject);
    child.once("spawn", () => {
      if (!elevated) {
        child.unref();
        resolve();
      }
    });
    if (elevated) {
      // Without -w, elevate exits after ShellExecute has accepted the installer.
      // Its own spawn event cannot prove UAC was accepted or the installer opened.
      child.once("exit", (code, signal) => {
        if (code === 0) resolve();
        else reject(new Error(`安装程序提权启动失败或已取消（${code ?? signal ?? "未知错误"}）。`));
      });
    }
  });
}

/** Keep upstream download/signature checks; leave quitting to the main process. */
export class RailWatchNsisUpdater extends NsisUpdater {
  async launchInstaller(): Promise<void> {
    const installer = this.installerPath;
    const helper = this.downloadedUpdateHelper;
    if (!installer || !helper?.downloadedFileInfo) {
      throw new Error("已下载的安装程序不可用，请重新检查更新。");
    }
    const args = ["--updated"];
    if (this.autoRunAppAfterInstall) args.push("--force-run");
    if (this.installDirectory) args.push(`/D=${this.installDirectory}`);
    if (helper.packageFile) args.push(`--package-file=${helper.packageFile}`);
    const elevate = () => launchProcess(path.join(process.resourcesPath, "elevate.exe"), [installer, ...args], true);
    if (helper.downloadedFileInfo.isAdminRightsRequired) {
      await elevate();
      return;
    }
    try {
      await launchProcess(installer, args);
    } catch (error) {
      const code = (error as NodeJS.ErrnoException).code;
      if (code !== "EACCES" && code !== "UNKNOWN") throw error;
      await elevate();
    }
  }
}
