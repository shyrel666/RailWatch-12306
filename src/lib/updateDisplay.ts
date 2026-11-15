import type { BoardTone } from "../components/DepartureBoard";
import type { AppInfo, MacArch, UpdateRuntimeState } from "../types";

export const LATEST_MAC_RELEASE_URL = "https://github.com/shyrel666/RailWatch-12306/releases/latest";

export type UpdateSignal = { tone: BoardTone; live: boolean };
export type UpdateFact = { label: string; value: string };

export function isRosettaMacApp(info?: AppInfo | null): boolean {
  return info?.platform === "darwin" && info.runningUnderARM64Translation === true;
}

export function hasDirectManualDownload(state: UpdateRuntimeState): boolean {
  if (state.installMode !== "manual" || !state.result?.ok || !state.result.hasUpdate) return false;
  return Boolean(state.result.downloadUrl && state.result.downloadUrl !== state.result.releaseUrl);
}

export function formatMacArchLabel(arch?: MacArch): string {
  return arch === "arm64" ? "Apple Silicon (arm64)" : arch === "x64" ? "Intel (x64)" : "当前芯片";
}

export function resolveNativeArm64DownloadUrl(state?: UpdateRuntimeState | null): string {
  const result = state?.result;
  if (result?.ok && result.targetArch === "arm64" && result.downloadUrl) {
    return result.downloadUrl;
  }
  return LATEST_MAC_RELEASE_URL;
}

/**
 * One lamp for every update entry point, so the sidebar, the About page and the
 * update panel agree: amber while something is pending, green when ready.
 */
export function getUpdateSignal(state: UpdateRuntimeState, installing = false): UpdateSignal {
  switch (state.phase) {
    case "checking":
    case "downloading":
      return { tone: "wait", live: true };
    case "available":
      return { tone: "wait", live: state.installMode !== "manual" };
    case "downloaded":
      if (installing) return { tone: "wait", live: true };
      return { tone: state.error ? "wait" : "go", live: false };
    case "not-available":
      return { tone: "go", live: false };
    case "error":
      return { tone: "stop", live: false };
    default:
      if (!state.result) return { tone: "idle", live: false };
      return { tone: !state.result.ok ? "stop" : state.result.hasUpdate ? "wait" : "go", live: false };
  }
}

const KB = 1024;
const MB = KB * 1024;
const GB = MB * 1024;

function byteUnit(bytes: number): [size: number, label: string, digits: number] {
  if (bytes >= GB) return [GB, "GB", 2];
  if (bytes >= MB) return [MB, "MB", 1];
  return [KB, "KB", 0];
}

export function formatBytes(bytes: number): string {
  const [size, label, digits] = byteUnit(bytes);
  return `${(bytes / size).toFixed(digits)} ${label}`;
}

/** "41.2 / 98.1 MB": both figures share the unit of the total. */
export function formatTransfer(transferred: number, total?: number): string {
  if (!total) return formatBytes(transferred);
  const [size, label, digits] = byteUnit(total);
  return `${(Math.min(transferred, total) / size).toFixed(digits)} / ${(total / size).toFixed(digits)} ${label}`;
}

export function formatRemaining(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "";
  if (seconds < 5) return "即将完成";
  if (seconds < 60) return `约 ${Math.ceil(seconds / 5) * 5} 秒`;
  if (seconds < 3600) return `约 ${Math.ceil(seconds / 60)} 分钟`;
  return `约 ${(seconds / 3600).toFixed(1)} 小时`;
}

/** Transfer figures for the departure-board facts row; empty when nothing is known. */
export function getUpdateFacts(state: UpdateRuntimeState): UpdateFact[] {
  if (state.phase === "downloaded" || (state.phase === "available" && state.installMode === "manual")) {
    return state.packageSize ? [{ label: "安装包", value: formatBytes(state.packageSize) }] : [];
  }
  if (state.phase !== "downloading" || state.downloadTransferred === undefined) return [];
  const { downloadTransferred: transferred, downloadTotal: total, downloadSpeed: speed } = state;
  const facts: UpdateFact[] = [{ label: "已下载", value: formatTransfer(transferred, total) }];
  if (speed) {
    facts.push({ label: "速度", value: `${formatBytes(speed)}/s` });
    const remaining = total ? formatRemaining((total - transferred) / speed) : "";
    if (remaining) facts.push({ label: "剩余", value: remaining });
  }
  return facts;
}

const releaseDateParts = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Shanghai", year: "numeric", month: "numeric", day: "numeric",
});

function dateParts(date: Date) {
  const parts = Object.fromEntries(releaseDateParts.formatToParts(date).map((part) => [part.type, part.value]));
  return { year: parts.year, month: parts.month, day: parts.day };
}

/** Release day in Beijing time, without the year when it is the current one. */
export function formatReleaseDate(value: string | undefined, now = new Date()): string {
  const date = value ? new Date(value) : null;
  if (!date || Number.isNaN(date.getTime())) return "";
  const release = dateParts(date);
  const day = `${release.month}月${release.day}日`;
  return release.year === dateParts(now).year ? day : `${release.year}年${day}`;
}
