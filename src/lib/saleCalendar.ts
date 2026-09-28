import type { StationSaleTimes } from "../types";
import { getTripDateStatus, isoDaysFromToday, PRESALE_WINDOW_DAYS, todayIso } from "./tripDate";

export const SALE_TIME_SOURCE = "https://kyfw.12306.cn/index/view/infos/sale_time.html";
export const saleStateLabels = {
  open: "已到起售时间", window: "预售期内", waiting: "待起售", future: "未进入预售期",
  unknown: "时间待核对", expired: "日期已过", invalid: "日期无效",
};
export type SaleDayState = keyof typeof saleStateLabels;

export function presaleDays(value?: number) {
  return value !== undefined && Number.isInteger(value) && value > 0 && value <= 366 ? value : PRESALE_WINDOW_DAYS;
}

export function saleDay(date: string, now: number, days: number, info: StationSaleTimes | null) {
  const windowDays = presaleDays(days);
  const offset = getTripDateStatus(date, new Date(now), windowDays).daysFromToday;
  if (offset === null) return { date, releaseDate: null, saleAt: null, time: null, state: "invalid" as SaleDayState };
  const releaseDate = isoDaysFromToday(1 - windowDays, new Date(`${date}T00:00:00+08:00`));
  const fresh = info?.status === "available" && info.checked_at !== null && info.expires_at !== null
    && now / 1000 >= info.checked_at && now / 1000 < info.expires_at;
  // The official page uses exclusive start/stop boundaries. Ambiguous or boundary records stay unknown.
  const matching = fresh ? info.schedules.filter(item => item.station_name === info.station
    && item.start_date < releaseDate && releaseDate < item.stop_date
    && /^(?:[01]\d|2[0-3]):[0-5]\d$/.test(item.sale_time)) : [];
  const choices = new Set(matching.map(item => `${item.station_code}/${item.sale_time}`));
  const time = choices.size === 1 ? matching[0].sale_time : null;
  const saleAt = time ? Date.parse(`${releaseDate}T${time}:00+08:00`) : null;
  let state: SaleDayState;
  if (offset < 0) state = "expired";
  else if (offset >= windowDays) state = "future";
  else if (offset < windowDays - 1) state = "window";
  else if (saleAt === null) state = "unknown";
  else state = now >= saleAt ? "open" : "waiting";
  return { date, releaseDate, saleAt, time, state };
}

export function calendarDays(now: number, days: number) {
  return Array.from({ length: presaleDays(days) + 7 }, (_, index) => isoDaysFromToday(index, new Date(now)));
}

export function countdown(saleAt: number, now: number) {
  const seconds = Math.max(0, Math.ceil((saleAt - now) / 1000));
  const days = Math.floor(seconds / 86400);
  const clock = [Math.floor(seconds % 86400 / 3600), Math.floor(seconds % 3600 / 60), seconds % 60]
    .map(value => String(value).padStart(2, "0")).join(":");
  return `${days ? `${days} 天 ` : ""}${clock}`;
}

export function beijingTimestamp(value: number) {
  const date = new Date(value);
  return `${todayIso(date)} ${new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai", hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
  }).format(date)}`;
}
