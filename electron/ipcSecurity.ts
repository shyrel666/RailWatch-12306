import path from "node:path";

export const RAILWATCH_COMMANDS = [
  "getRuntimeInfo",
  "loadConfig",
  "saveConfig",
  "checkEnvironment",
  "downloadChromeDriver",
  "openLogin",
  "analyzeQuery",
  "startMonitor",
  "stopMonitor",
  "closeBrowser",
  "clearLocalData",
  "exportLog",
  "clearLog",
  "loadPreferences",
  "savePreferences",
] as const;

export type RailWatchCommandName = (typeof RAILWATCH_COMMANDS)[number];

export type ConfirmationPrompt = {
  title: string;
  message: string;
};

const commandSet = new Set<string>(RAILWATCH_COMMANDS);

export function isRailWatchCommand(command: unknown): command is RailWatchCommandName {
  return typeof command === "string" && commandSet.has(command);
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

export function isTrustedRailWatchUrl(frameUrl: string, allowedRendererUrl: string): boolean {
  try {
    const frame = new URL(frameUrl);
    const allowed = new URL(allowedRendererUrl);
    if (allowed.protocol === "file:") {
      return frame.href === allowed.href;
    }
    return frame.origin === allowed.origin;
  } catch {
    return false;
  }
}

export function getCommandConfirmation(command: RailWatchCommandName, payload: Record<string, unknown>): ConfirmationPrompt | null {
  if (command === "clearLocalData") {
    return {
      title: "清除本地数据",
      message: "此操作将删除本地 RailWatch 配置、日志和 Chrome 配置。是否继续？",
    };
  }
  if (command === "closeBrowser") {
    return {
      title: "关闭浏览器",
      message: "是否关闭受控的 Chrome 会话？",
    };
  }
  if (command === "startMonitor") {
    const config = isRecord(payload.config) ? payload.config : payload;
    if (Boolean(config.auto_submit) || Boolean(config.auto_alternate)) {
      return {
        title: "确认自动化",
        message: "你已启用自动提交或自动候补。请确认是否允许本次自动化操作。",
      };
    }
  }
  return null;
}

function normalizeExportPath(filePath: string): string {
  return path.resolve(filePath);
}

export function recordExportPathGrant(filePath: string | null | undefined, grants: Set<string>): void {
  if (filePath) {
    grants.add(normalizeExportPath(filePath));
  }
}

export function isExportPathAllowed(
  command: RailWatchCommandName,
  payload: Record<string, unknown>,
  grants: Set<string>,
): boolean {
  if (command !== "exportLog" || typeof payload.path !== "string" || !payload.path) {
    return true;
  }
  return grants.has(normalizeExportPath(payload.path));
}

export function consumeExportPathGrant(command: RailWatchCommandName, payload: Record<string, unknown>, grants: Set<string>): void {
  if (command === "exportLog" && typeof payload.path === "string" && payload.path) {
    grants.delete(normalizeExportPath(payload.path));
  }
}
