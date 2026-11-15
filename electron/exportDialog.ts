import os from "node:os";
import path from "node:path";
import { readdir, stat, lstat, access } from "node:fs/promises";
import { constants, type Dirent } from "node:fs";

export type ExportRoot = { name: string; path: string };

/** Normalize bare Windows drive references like "D:" to "D:\\" so path checks treat them as root paths. */
export function normalizeExportPathInput(value: string, platform: NodeJS.Platform = process.platform): string {
  const trimmed = value.trim();
  if (platform === "win32" && /^[A-Za-z]:$/.test(trimmed)) {
    return `${trimmed.toUpperCase()}\\`;
  }
  return trimmed;
}

const DEFAULT_DRIVE_PROBE_TIMEOUT_MS = 1000;

type AccessCheck = (target: string) => Promise<void>;

const defaultAccessCheck: AccessCheck = (target) => access(target, constants.F_OK);

/**
 * Probes that have not settled yet, per access function. The timeout below only
 * stops waiting: an fs.access on a disconnected drive keeps its libuv worker
 * thread until the OS gives up. Sharing the running probe keeps that to one
 * thread per drive, however often the dialog is opened.
 */
const runningDriveProbes = new WeakMap<AccessCheck, Map<string, Promise<void>>>();

function sharedDriveProbe(target: string, checkAccess: AccessCheck): Promise<void> {
  let running = runningDriveProbes.get(checkAccess);
  if (!running) {
    running = new Map();
    runningDriveProbes.set(checkAccess, running);
  }
  const existing = running.get(target);
  if (existing) return existing;
  const probes = running;
  const probe = Promise.resolve()
    .then(() => checkAccess(target))
    .finally(() => { probes.delete(target); });
  probes.set(target, probe);
  return probe;
}

async function probeDriveAccess(
  target: string,
  checkAccess: AccessCheck,
  timeoutMs: number,
): Promise<boolean> {
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) {
    try {
      await sharedDriveProbe(target, checkAccess);
      return true;
    } catch {
      return false;
    }
  }

  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    await Promise.race([
      sharedDriveProbe(target, checkAccess),
      new Promise<never>((_, reject) => {
        timer = setTimeout(() => reject(new Error(`Timed out probing ${target}`)), timeoutMs);
      }),
    ]);
    return true;
  } catch {
    return false;
  } finally {
    if (timer !== undefined) {
      clearTimeout(timer);
    }
  }
}

/** Probe accessible disk drives (Windows) or root/mounted volumes (macOS/Linux) without UI popups. */
export async function listExportRoots(options?: {
  platform?: NodeJS.Platform;
  accessFn?: (target: string) => Promise<void>;
  readdirFn?: (target: string) => Promise<Dirent[]>;
  homeDir?: string;
  timeoutMs?: number;
}): Promise<ExportRoot[]> {
  const platform = options?.platform ?? process.platform;
  const checkAccess = options?.accessFn ?? defaultAccessCheck;
  const readEntries = options?.readdirFn ?? ((target: string) => readdir(target, { withFileTypes: true }));
  const homeDir = options?.homeDir ?? os.homedir();
  const timeoutMs = options?.timeoutMs ?? DEFAULT_DRIVE_PROBE_TIMEOUT_MS;

  if (platform === "win32") {
    const candidates = Array.from({ length: 26 }, (_, index) => `${String.fromCharCode(65 + index)}:\\`);
    const checks = await Promise.all(
      candidates.map(async (rootPath) => {
        const accessible = await probeDriveAccess(rootPath, checkAccess, timeoutMs);
        return accessible ? { name: rootPath, path: rootPath } : null;
      }),
    );
    return checks.filter((item): item is ExportRoot => item !== null);
  }

  const roots: ExportRoot[] = [{ name: "根目录 /", path: "/" }];
  if (homeDir && homeDir !== "/") {
    roots.push({ name: "主目录", path: homeDir });
  }
  const volumeBases = platform === "darwin" ? ["/Volumes"] : ["/mnt", "/media"];
  for (const base of volumeBases) {
    try {
      const entries = await readEntries(base);
      const mounted = entries
        .filter((entry) => entry.isDirectory() && !entry.name.startsWith("."))
        .sort((a, b) => a.name.localeCompare(b.name, "zh-CN", { numeric: true }))
        .map((entry) => ({ name: entry.name, path: path.posix.join(base, entry.name) }));
      roots.push(...mounted);
    } catch {
      /* Volume root absent or unreadable; skip cleanly. */
    }
  }
  return roots;
}

/** Only directory names and text-file names are exposed to the export picker. */
export async function listExportDirectory(value: unknown) {
  if (typeof value !== "string") throw new Error("请输入完整的文件夹路径。");
  const normalizedInput = normalizeExportPathInput(value);
  if (!normalizedInput || !path.isAbsolute(normalizedInput)) throw new Error("请输入完整的文件夹路径。");
  const directory = path.normalize(normalizedInput);
  const entries = await readdir(directory, { withFileTypes: true });
  return {
    directory, parent: path.dirname(directory),
    folders: entries.filter(entry => entry.isDirectory())
      .sort((a, b) => a.name.localeCompare(b.name, "zh-CN", { numeric: true }))
      .map(entry => ({ name: entry.name, path: path.join(directory, entry.name) })),
    files: entries.filter(entry => entry.isFile() && /\.txt$/i.test(entry.name))
      .map(entry => entry.name).sort((a, b) => a.localeCompare(b, "zh-CN", { numeric: true })),
  };
}

export async function validateLogExport(directory: unknown, name: unknown) {
  if (typeof directory !== "string") throw new Error("请选择有效的文件夹。");
  const targetDir = normalizeExportPathInput(directory);
  if (!targetDir || !path.isAbsolute(targetDir)) throw new Error("请选择有效的文件夹。");
  if (typeof name !== "string" || !name.trim() || name !== name.trim() ||
      /[<>:"/\\|?*\x00-\x1f]/.test(name) || /[. ]$/.test(name) ||
      /^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(name)) {
    throw new Error("请输入有效的文件名，不能包含路径或特殊字符。");
  }
  const fileName = /\.txt$/i.test(name) ? name : `${name}.txt`;
  if (!(await stat(targetDir)).isDirectory()) throw new Error("保存位置不是文件夹。");
  await access(targetDir, constants.W_OK);
  const filePath = path.join(targetDir, fileName);
  let exists = false;
  try {
    const entry = await lstat(filePath);
    if (!entry.isFile() || entry.isSymbolicLink()) throw new Error("该位置不能保存日志，请使用其他文件名。");
    exists = true;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
  }
  return { filePath, exists };
}
