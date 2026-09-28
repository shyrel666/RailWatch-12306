import path from "node:path";
import { readdir, stat, lstat, access } from "node:fs/promises";
import { constants } from "node:fs";

/** Only directory names and text-file names are exposed to the export picker. */
export async function listExportDirectory(value: unknown) {
  if (typeof value !== "string" || !path.isAbsolute(value)) throw new Error("请输入完整的文件夹路径。");
  const directory = path.normalize(value);
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
  if (typeof directory !== "string" || !path.isAbsolute(directory)) throw new Error("请选择有效的文件夹。");
  if (typeof name !== "string" || !name.trim() || name !== name.trim() ||
      /[<>:"/\\|?*\x00-\x1f]/.test(name) || /[. ]$/.test(name) ||
      /^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(name)) {
    throw new Error("请输入有效的文件名，不能包含路径或特殊字符。");
  }
  const fileName = /\.txt$/i.test(name) ? name : `${name}.txt`;
  if (!(await stat(directory)).isDirectory()) throw new Error("保存位置不是文件夹。");
  await access(directory, constants.W_OK);
  const filePath = path.join(directory, fileName);
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
