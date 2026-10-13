import { createHash, randomUUID } from "node:crypto";
import { mkdir, open, realpath, rename, unlink, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

export const ALERT_SOUND_TONES = ["beep", "chime", "double", "alarm", "custom"] as const;
export type AlertSoundTone = (typeof ALERT_SOUND_TONES)[number];
export type AlertSoundSelection = { sound_tone?: AlertSoundTone; sound_custom_file?: string };
export const MAX_SOUND_BYTES = 10 * 1024 * 1024;
const importedFilePattern = /^[a-f0-9]{64}\.(wav|mp3|ogg|m4a)$/;

export function isAlertSoundTone(value: unknown): value is AlertSoundTone {
  return typeof value === "string" && ALERT_SOUND_TONES.includes(value as AlertSoundTone);
}

export function isImportedSoundFile(value: unknown): value is string {
  return typeof value === "string" && importedFilePattern.test(value);
}

// Match Python's get_data_path, including Windows LOCALAPPDATA rather than Roaming.
export function notificationSoundDirectory(): string {
  const base = process.platform === "win32"
    ? process.env.LOCALAPPDATA || path.join(os.homedir(), "AppData", "Local")
    : process.platform === "darwin"
      ? path.join(os.homedir(), "Library", "Application Support")
      : process.env.XDG_DATA_HOME || path.join(os.homedir(), ".local", "share");
  return path.join(base, "railwatch-12306", "notification-sounds");
}

async function readBoundedFile(filePath: string): Promise<Buffer> {
  const handle = await open(filePath, "r");
  try {
    const stat = await handle.stat();
    if (!stat.isFile() || stat.size === 0 || stat.size > MAX_SOUND_BYTES) {
      throw new Error("提示音文件须为非空音频，大小不超过 10 MB。");
    }
    // Bound the read even if the source file changes after stat.
    const data = Buffer.alloc(stat.size + 1);
    let read = 0;
    while (read < data.length) {
      const { bytesRead } = await handle.read(data, read, data.length - read, read);
      if (!bytesRead) break;
      read += bytesRead;
    }
    if (read !== stat.size) throw new Error("音频文件发生变化，请重新选择。");
    return data.subarray(0, read);
  } finally {
    await handle.close();
  }
}

export async function prepareSoundImport(filePath: string) {
  const extension = path.extname(filePath).toLowerCase();
  if (![".wav", ".mp3", ".ogg", ".m4a"].includes(extension)) {
    throw new Error("请选择 WAV、MP3、OGG 或 M4A 音频文件。");
  }
  const data = await readBoundedFile(filePath);
  const file = createHash("sha256").update(data).digest("hex") + extension;
  const name = Array.from(path.basename(filePath).replace(/[\r\n\x00-\x1f]/g, "")).slice(0, 160).join("");
  return { file, name, data, audio: data.toString("base64") };
}

export async function storeImportedSound(asset: { file: string; data: Buffer }, directory = notificationSoundDirectory()): Promise<void> {
  if (!isImportedSoundFile(asset.file)) throw new Error("自定义提示音文件无效。");
  await mkdir(directory, { recursive: true });
  const temporary = path.join(directory, `${asset.file}.${randomUUID()}.tmp`);
  try {
    await writeFile(temporary, asset.data, { flag: "wx", mode: 0o600 });
    await rename(temporary, path.join(directory, asset.file));
  } catch (error) {
    await unlink(temporary).catch(() => undefined);
    throw error;
  }
}

export async function readImportedSound(file: unknown, directory = notificationSoundDirectory()): Promise<string> {
  if (!isImportedSoundFile(file)) throw new Error("请先导入自定义提示音。");
  const target = path.join(directory, file);
  try {
    const [root, resolved] = await Promise.all([realpath(directory), realpath(target)]);
    if (path.dirname(resolved) !== root) throw new Error("自定义提示音路径无效。");
    const data = await readBoundedFile(resolved);
    const digest = createHash("sha256").update(data).digest("hex");
    if (!file.startsWith(digest + ".")) throw new Error("自定义提示音已变更，请重新导入。");
    return data.toString("base64");
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      throw new Error("自定义提示音文件已丢失，请重新导入。");
    }
    throw error;
  }
}
