import type { RailWatchConfig } from "../types";

export const DEFAULT_ALTERNATE_DEADLINE = "开车前1小时";

export function deadlineMinutes(value: string): number | null {
  const match = /^开车前\s*(\d+)\s*(分钟|小时|天)$/.exec(value.trim());
  return match ? Number(match[1]) * ({ 分钟: 1, 小时: 60, 天: 1440 }[match[2]] ?? 1) : null;
}

export function canonicalDeadline(value: string): string {
  const minutes = deadlineMinutes(value);
  if (!minutes || !Number.isSafeInteger(minutes)) return value.trim();
  return minutes % 1440 === 0 ? `开车前${minutes / 1440}天` : minutes % 60 === 0
    ? `开车前${minutes / 60}小时` : `开车前${minutes}分钟`;
}

export function alternateDates(config: Pick<RailWatchConfig, "date" | "date_range">): string[] {
  const day = Date.parse(`${config.date}T00:00:00Z`);
  if (!Number.isFinite(day) || new Date(day).toISOString().slice(0, 10) !== config.date) return [];
  const radius = config.date_range === "±2天" ? 2 : config.date_range === "±1天" ? 1 : 0;
  return Array.from({ length: 2 * radius + 1 }, (_, i) => new Date(day + (i - radius) * 86400000).toISOString().slice(0, 10));
}

export function alternateConfigIssue(config: RailWatchConfig): string | null {
  if (!config.auto_alternate) return null;
  if (!deadlineMinutes(config.alternate_deadline)) return "请重新选择截止兑现时间，仅支持官网提供的选项。";
  if (!config.alternate_accept_new_trains) return null;
  const windows = config.alternate_new_train_windows ?? [];
  if (!windows.length) return "接受新增列车时，请设置至少一个日期和出发时段。";
  if (windows.length > 3) return "新增列车最多设置3个日期";
  if (new Set(windows.map(w => w.date)).size !== windows.length) return "新增列车日期不能重复";
  if (windows.some(w => !Number.isInteger(w.start_hour) || !Number.isInteger(w.end_hour) ||
    w.start_hour < 0 || w.start_hour >= w.end_hour || w.end_hour > 24)) return "新增列车时段须为0至24点内的整点，开始早于结束";
  const dates = alternateDates(config);
  if (windows.some(w => !dates.includes(w.date))) return "新增列车日期须在当前行程日期范围内，请重新选择。";
  return null;
}

export function officialReadTime(value?: number | null) {
  return value == null ? "未记录" : new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai",
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(new Date(value * 1000));
}
