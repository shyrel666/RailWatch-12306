import path from "node:path";
import type { ConfirmationPrompt } from "./confirmationBridge";

export const RAILWATCH_COMMANDS = [
  "retryRuntime",
  "getRuntimeInfo",
  "loadConfig",
  "saveConfig",
  "loadTripState",
  "saveTripDraft",
  "searchStations",
  "refreshStations",
  "stationSaleTimes",
  "loadTripChoices",
  "saveTrainFavorites",
  "readPassengers",
  "checkEnvironment",
  "downloadChromeDriver",
  "openLogin",
  "checkLogin",
  "rehearse",
  "cancelRehearsal",
  "rehearsalHistory",
  "clearRehearsalHistory",
  "runReviews",
  "runReview",
  "analyzeQuery",
  "startMonitor",
  "stopMonitor",
  "taskActivity",
  "continueOrder",
  "orderHistory",
  "orderDetail",
  "dismissOrder",
  "closeBrowser",
  "clearLocalData",
  "exportLog",
  "clearLog",
  "loadPreferences",
  "savePreferences",
  "notificationStatus",
  "testNotification",
  "syncServerTime",
] as const;

export type RailWatchCommandName = (typeof RAILWATCH_COMMANDS)[number];

export type { ConfirmationPrompt } from "./confirmationBridge";

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

const ALLOWED_EXTERNAL_HOSTS = new Set(["github.com"]);

export function isAllowedExternalUrl(value: unknown): value is string {
  if (typeof value !== "string") {
    return false;
  }
  try {
    const url = new URL(value);
    if (url.origin === "https://kyfw.12306.cn" && url.pathname === "/index/view/infos/sale_time.html"
        && !url.username && !url.password && !url.search && !url.hash) return true;
    return url.protocol === "https:" && ALLOWED_EXTERNAL_HOSTS.has(url.hostname.toLowerCase());
  } catch {
    return false;
  }
}

export function getCommandConfirmation(command: RailWatchCommandName, payload: Record<string, unknown>): ConfirmationPrompt | null {
  if (command === "clearRehearsalHistory") {
    return { title: "清除彩排记录", message: "清除全部本地彩排报告及其预测数据？清除后无法恢复，订单和实战复盘记录会保留。" };
  }
  if (command === "rehearse") {
    const config = isRecord(payload.config) ? payload.config : payload;
    const remaining = typeof config.sale_at === "string" ? Date.parse(config.sale_at) - Date.now() : Infinity;
    return { title: "开始起售彩排", message: "彩排会打开 12306 乘车人页面和余票查询页，并进行 1 次查询；交易步骤只在本地断网页面中演练，不会在官方页面点击预订或提交，也不会创建订单。是否继续？"
      + (remaining >= 0 && remaining < 900_000 ? "\n距离起售不足 15 分钟，请留意准备时间。" : "") };
  }
  if (command === "dismissOrder") {
    return {
      title: "结束本次核对",
      message: "结束后可重新启动监控，并保留本地历史记录。此操作不会取消12306订单；如曾提交或手动下单，请先在官方页面核对并处理。是否继续？",
    };
  }
  if (command === "clearLocalData") {
    return {
      title: "清除本地数据",
      okText: "清除数据", danger: true,
      message: "将关闭 RailWatch 受控浏览器，并删除本地配置、登录信息、订单与复盘记录、日志和下载的驱动。不会取消官方订单。是否继续？",
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
    const dates = Array.isArray(payload.expected_dates) ? payload.expected_dates.join("、") : String(config.date || "未指定");
    return {
      title: "核对本次监控",
      message: [
        `执行日期：${dates}`,
        `路线：${config.from_station_cn || "未指定"} → ${config.to_station_cn || "未指定"}`,
        `车次优先顺序：${config.train_code || "不限"}`,
        `席别优先顺序：${config.seat_keyword || "不限"}`,
        `乘客：${config.passengers || "未指定"}`,
        `起售时刻：${config.timer_enabled ? config.sale_at || "未设置" : "未启用定时"}`,
        `自动提交：${config.auto_submit ? "开" : "关"}；自动候补：${config.auto_alternate ? "开" : "关"}`,
        "确认后按上述配置启动。核验和支付仍需在官方页面完成。",
      ].join("\n"),
    };
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
